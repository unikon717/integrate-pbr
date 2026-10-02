"""Fixed-scale, mask-aware offline diagnostics for the scratch checkpoint."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from .usage import DEFAULT_CONTRACT, load_usage_contract, resolve_surface_usage
from .preprocess import LEGACY_ALPHA_PREPROCESS_VERSION

DEFAULT_IDS = (
    "ref-8cfea7ffb5830841-ad476ecb09",
    "ref-8d14467a3cb2953d-f1fc16dfcc",
    "ref-7969e7de5d7cf3fc-a228806e38",
    "ref-3c712c67186210ca-0039894e20",
    "ref-868e4a00cceb8e26-442802c1a6",
    "ref-932705109984973e-35a7bfcc94",
    "ref-1703566f6e4773cc-fc4673695a",
)
SCALARS = ("base_depth", "smoothness", "dielectric_f0", "ao")
CHANNELS = (*SCALARS, "metal_type")
EXPECTED_WEIGHT_HASH = "377c685f2db0e7a9dd26984b8e4b3bf35dfe89f80a75da42e6fd8dca079f8e27"
EXPECTED_WEIGHT_BYTES = 6135740
CELL = 256
HEADER = 56
ROW = CELL + 32
MASK_RGB = (255, 0, 255)
PALETTE = ((50, 50, 50), (173, 204, 255), (255, 217, 66), (147, 220, 196),
           (234, 235, 245), (218, 121, 84), (108, 133, 156), (221, 213, 186),
           (192, 205, 217), (248, 145, 213), (133, 190, 255), (243, 174, 88))
DOOR_ITEM_ID = "ref-798f833c142424e5-ad420d8c73"
DOOR_ITEM_ENTRY = "assets/minecraft/textures/item/birch_door.png"
DOOR_TOP_ID, DOOR_BOTTOM_ID = DEFAULT_IDS[4:6]
DOOR_TOP_ENTRY = "assets/minecraft/textures/block/birch_door_top.png"
DOOR_BOTTOM_ENTRY = "assets/minecraft/textures/block/birch_door_bottom.png"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def choose_rows(rows: list[dict], sample_ids=DEFAULT_IDS) -> list[dict]:
    indexed = {}
    for row in rows:
        sample_id = row["sample_id"]
        if sample_id in indexed:
            raise ValueError(f"duplicate sample_id: {sample_id}")
        indexed[sample_id] = row
    missing = [sample_id for sample_id in sample_ids if sample_id not in indexed]
    if missing:
        raise ValueError(f"selected validation IDs absent: {missing}")
    return [indexed[sample_id] for sample_id in sample_ids]


def usage_for_selected_row(row: dict, contract: dict) -> dict:
    """Attach exact-identity usage guidance without running model inference."""
    return resolve_surface_usage(resource_id=row.get("source"), sample_id=row["sample_id"],
                                 reference_entry=row.get("reference_entry"),
                                 evidence=row.get("usage_evidence", ()), contract=contract)


def scalar_measure(target: np.ndarray, prediction: np.ndarray, valid: np.ndarray) -> dict:
    mask = valid & np.isfinite(target)
    count = int(mask.sum())
    absolute = np.abs(target[mask].astype(np.float64) - prediction[mask].astype(np.float64))
    total = float(absolute.sum())
    return {"support_pixels": count, "absolute_error_sum": total,
            "mae": total / count if count else None}


def _resolve(root: Path, relative: str) -> Path:
    path = (root / relative).resolve()
    if root not in path.parents:
        raise ValueError(f"dataset path escapes root: {relative}")
    return path


def _file_identity(path: Path, expected: str | None = None) -> dict:
    actual = sha256(path)
    return {"path": str(path.resolve()), "sha256": actual, "bytes": path.stat().st_size,
            "training_sha256": expected, "matches_training": actual == expected if expected else None}


def _verify_inputs(root: Path, manifest: Path, weights: Path, labels: Path,
                   output: Path) -> tuple[list[dict], dict, dict]:
    if output.exists():
        raise FileExistsError(f"output directory already exists: {output}")
    for path in (root, manifest, weights, labels):
        if not path.exists():
            raise FileNotFoundError(path)
    run_path = weights.parent / "run-manifest.json"
    if not run_path.exists():
        raise FileNotFoundError(run_path)
    run = json.loads(run_path.read_text("utf-8"))
    if weights.stat().st_size != EXPECTED_WEIGHT_BYTES or sha256(weights) != EXPECTED_WEIGHT_HASH:
        raise ValueError("checkpoint bytes or SHA-256 differ from the approved scratch checkpoint")
    if run["model"]["sha256"] != EXPECTED_WEIGHT_HASH or run["model"]["bytes"] != EXPECTED_WEIGHT_BYTES:
        raise ValueError("training run manifest identifies another checkpoint")
    for key, path in (("validation_manifest", manifest), ("labels", labels)):
        if sha256(path) != run["input_sha256"][key]:
            raise ValueError(f"{key} raw bytes disagree with training run manifest")
    rows = [json.loads(line) for line in manifest.read_text("utf-8").splitlines() if line.strip()]
    selected = choose_rows(rows)
    files = run["input_sha256"]["assets"]["files"]
    for row in selected:
        for key in ("source", "targets"):
            path = _resolve(root, row[key])
            if not path.is_file() or sha256(path) != files.get(row[key]):
                raise ValueError(f"selected {key} raw bytes disagree with training run manifest: {row[key]}")
    repo = Path(__file__).resolve().parents[3]
    code = {}
    for name in ("__main__.py", "dataset.py", "network.py", "training.py", "diagnostics.py", "preprocess.py"):
        path = repo / "engine/src/integratepbr_engine" / name
        key = path.relative_to(repo).as_posix()
        code[key] = _file_identity(path, run["code_sha256"]["files"].get(key))
    path = repo / "engine/pyproject.toml"
    key = path.relative_to(repo).as_posix()
    code[key] = _file_identity(path, run["code_sha256"]["files"].get(key))
    for name in ("network.py",):
        key = f"engine/src/integratepbr_engine/{name}"
        if not code[key]["matches_training"]:
            raise ValueError(f"{name} differs from training snapshot")
    return selected, run, code


def _gray(values: np.ndarray, mask: np.ndarray) -> Image.Image:
    safe = np.nan_to_num(values, nan=0.0)
    gray = np.rint(np.clip(safe, 0, 1) * 255).astype(np.uint8)
    rgb = np.repeat(gray[:, :, None], 3, axis=2)
    rgb[~mask] = MASK_RGB
    return Image.fromarray(rgb, "RGB")


def _class_image(values: np.ndarray, mask: np.ndarray) -> Image.Image:
    rgb = np.zeros((*values.shape, 3), dtype=np.uint8)
    for index in np.unique(values[mask]):
        rgb[mask & (values == index)] = PALETTE[int(index) % len(PALETTE)]
    rgb[~mask] = MASK_RGB
    return Image.fromarray(rgb, "RGB")


def make_sheet(channel: str, rows: list[dict], labels: dict, output: Path) -> None:
    width = 4 * CELL
    sheet = Image.new("RGB", (width, HEADER + len(rows) * ROW), (30, 30, 34))
    draw = ImageDraw.Draw(sheet)
    names = ("Original RGBA", "Sanitized reference", "Raw prediction", "Absolute error")
    for col, name in enumerate(names):
        draw.text((col * CELL + 8, 12), name, fill="white")
    draw.text((8, 33), f"{channel} | fixed 0..1 gray | magenta = unsupported", fill="white")
    for index, item in enumerate(rows):
        y = HEADER + index * ROW
        rgba = item["rgba"]
        source = Image.new("RGBA", rgba.size, (220, 220, 220, 255))
        source.alpha_composite(rgba)
        images = [source.convert("RGB")]
        target, pred, mask = item["target"], item["prediction"], item["mask"]
        if channel == "metal_type":
            images.extend((_class_image(target, mask), _class_image(pred, mask),
                           _class_image((target != pred).astype(np.uint8), mask)))
        else:
            images.extend((_gray(target, mask), _gray(pred, mask),
                           _gray(np.abs(target - pred), mask)))
        for col, panel in enumerate(images):
            panel.thumbnail((CELL, CELL), Image.Resampling.NEAREST)
            enlarged = panel.resize((CELL, CELL), Image.Resampling.NEAREST)
            sheet.paste(enlarged, (col * CELL, y))
        draw.text((8, y + CELL + 7), item["label"], fill="white")
    sheet.save(output, format="PNG")


def make_door_preview(top: Image.Image, bottom: Image.Image, output: Path,
                      scale: int = 4) -> dict:
    if top.size != bottom.size or scale < 1 or int(scale) != scale:
        raise ValueError("door halves must have matching dimensions and integer display scale")
    width, height = top.size
    preview = Image.new("RGBA", (width, 2 * height))
    preview.paste(top.convert("RGBA"), (0, 0))
    preview.paste(bottom.convert("RGBA"), (0, height))
    preview.resize((width * scale, 2 * height * scale), Image.Resampling.NEAREST).save(output)
    return {"filename": output.name, "layout": f"top directly above bottom; boundary at native y={height}",
            "source_ids": [DOOR_TOP_ID, DOOR_BOTTOM_ID],
            "native_dimensions": {"width": width, "height": 2 * height},
            "display_dimensions": {"width": width * scale, "height": 2 * height * scale},
            "resize": "nearest neighbor"}


def diagnose(dataset_root: Path, manifest: Path, weights: Path, labels_path: Path,
             output: Path, *, cpu: bool = True) -> dict:
    """Validate identities before writing, then render exact validation rows."""
    root = dataset_root.resolve()
    selected, run, code = _verify_inputs(root, manifest, weights, labels_path, output)
    usage_contract = load_usage_contract()
    import torch
    from safetensors.torch import load_file
    from .dataset import ReviewedTextureDataset, collate_native
    from .network import ContextSwinUNet

    labels = json.loads(labels_path.read_text("utf-8"))
    dataset = ReviewedTextureDataset(root, manifest, material_classes=len(labels["materials"]),
                                     structure_classes=len(labels["structures"]),
                                     object_classes=len(labels["objects"]),
                                     metal_classes=len(labels["metals"]),
                                     preprocessing_version=LEGACY_ALPHA_PREPROCESS_VERSION)
    index = {row["sample_id"]: i for i, row in enumerate(dataset.rows)}
    model = ContextSwinUNet(len(labels["materials"]), len(labels["structures"]),
                            len(labels["objects"]), len(labels["metals"]))
    model.load_state_dict(load_file(str(weights), device="cpu"), strict=True)
    device = torch.device("cpu" if cpu or not torch.cuda.is_available() else "cuda")
    model.to(device).eval()
    samples = []
    panels = {name: [] for name in CHANNELS}
    totals = {name: {"support_pixels": 0, "absolute_error_sum": 0.0, "correct_pixels": 0,
                     "per_class_support": {label: 0 for label in labels["metals"]}}
              for name in CHANNELS}
    with torch.inference_mode():
        for row in selected:
            sample = dataset[index[row["sample_id"]]]
            batch = collate_native([sample])
            prediction = model(batch["image"].to(device), batch["metadata"].to(device),
                               batch["name_bytes"].to(device))
            height, width = sample["image"].shape[1:]
            valid = sample["image"][4].numpy() > 0.5
            source_path = _resolve(root, row["source"])
            target_path = _resolve(root, row["targets"])
            with Image.open(source_path) as opened:
                rgba = opened.convert("RGBA").copy()
            metrics = {}
            for name in CHANNELS:
                target = sample["targets"][name].numpy()
                if name == "metal_type":
                    pred = prediction.metal_type.argmax(1)[0, :height, :width].cpu().numpy()
                    mask = valid & np.isfinite(target) & (target != 255)
                    count = int(mask.sum())
                    correct = int((target[mask] == pred[mask]).sum())
                    support = {label: int((target[mask] == i).sum())
                               for i, label in enumerate(labels["metals"])}
                    metrics[name] = {"support_pixels": count,
                                     "accuracy": correct / count if count else None,
                                     "correct_pixels": correct, "per_class_support": support}
                    totals[name]["correct_pixels"] += correct
                    for label, value in support.items():
                        totals[name]["per_class_support"][label] += value
                else:
                    pred = getattr(prediction, name)[0, 0, :height, :width].cpu().numpy()
                    mask = valid & np.isfinite(target)
                    metrics[name] = scalar_measure(target, pred, valid)
                    totals[name]["absolute_error_sum"] += metrics[name]["absolute_error_sum"]
                    if name == "base_depth":
                        metrics[name]["mae_labpbr_alpha_steps"] = (
                            metrics[name]["mae"] * 255 if metrics[name]["mae"] is not None else None)
                totals[name]["support_pixels"] += metrics[name]["support_pixels"]
                panels[name].append({"rgba": rgba, "target": target,
                                     "prediction": pred, "mask": mask,
                                     "label": f"{row['name']} | {row['sample_id']} | {width}x{height}"})
            samples.append({"sample_id": row["sample_id"], "name": row.get("name"),
                            "mod_id": row.get("mod_id"), "material_family": row.get("material_family"),
                            "source_artwork_id": row.get("source_artwork_id"),
                            "derivative_group": row.get("derivative_group"),
                            "reviewed": row.get("reviewed"),
                            "supervision_source": row.get("supervision_source"),
                            "target_provenance": row.get("target_provenance"),
                            "reference_entry": row["reference_entry"],
                            "dimensions": {"width": width, "height": height},
                            "source": _file_identity(source_path, run["input_sha256"]["assets"]["files"][row["source"]]),
                            "targets": _file_identity(target_path, run["input_sha256"]["assets"]["files"][row["targets"]]),
                            "metrics": metrics,
                            "usage": usage_for_selected_row(row, usage_contract)})
    output.mkdir(parents=True, exist_ok=False)
    sheets = {}
    for name in CHANNELS:
        count = totals[name]["support_pixels"]
        if name == "metal_type":
            totals[name]["accuracy"] = totals[name]["correct_pixels"] / count if count else None
        else:
            totals[name]["mae"] = totals[name]["absolute_error_sum"] / count if count else None
            if name == "base_depth":
                totals[name]["mae_labpbr_alpha_steps"] = (
                    totals[name]["mae"] * 255 if count else None)
        if count:
            filename = f"{name}.png"
            make_sheet(name, panels[name], labels, output / filename)
            sheets[name] = filename
        else:
            sheets[name] = {"omitted": "zero supported opaque labels"}
    by_id = {row["sample_id"]: row for row in selected}
    door_pair = {"top": {"sample_id": DOOR_TOP_ID, "reference_entry": by_id[DOOR_TOP_ID]["reference_entry"]},
                 "bottom": {"sample_id": DOOR_BOTTOM_ID, "reference_entry": by_id[DOOR_BOTTOM_ID]["reference_entry"]}}
    with Image.open(_resolve(root, by_id[DOOR_TOP_ID]["source"])) as top, Image.open(
            _resolve(root, by_id[DOOR_BOTTOM_ID]["source"])) as bottom:
        door_preview = make_door_preview(top, bottom, output / "birch-door-placed-preview.png")
    annotation_note = {
        "source": "user guidance", "reviewed": False,
        "observations": ["The item texture is a held item icon.",
                         "Broad wood roughness suffices for the item icon.",
                         "The two block textures are the placed door's upper and lower parts and are the detailed PBR visual-review priority.",
                         "The large pale upper interior panel is wood; left and right dark-gray patches are metal fittings."],
        "scope": "High-level guidance only; no pixel material, structure, depth, or numeric roughness training supervision."
    }
    (output / "annotation-note.json").write_text(
        json.dumps(annotation_note, indent=2, ensure_ascii=False) + "\n", "utf-8")
    report = {"scope": "historical legacy checkpoint diagnosis; incompatible with corrected inference; same-source unreviewed exact-reference offline diagnosis",
              "preprocessing_version": LEGACY_ALPHA_PREPROCESS_VERSION,
              "prediction": "raw network output; not final constrained/rendered LabPBR maps",
              "limitations": ["Cannot certify motifs, seams, rings, height rules, game rendering, visual acceptance, or deployability.",
                              "The historical loader alpha transform is explicitly reproduced by the legacy helper; input alpha is approximately 0..1/255, while validity is correct. The current loader differs from the training snapshot; this is not an exact historical whole-code replay."],
              "not_evaluated": {name: "effective labels absent" for name in
                                ("object_type", "structure", "boundary_x", "boundary_y", "fine_depth")},
              "material_supervision": "object-material and local material labels provide metal-positive evidence only; no general semantic/material accuracy",
              "rendering": {"cell_pixels": CELL, "resize": "nearest neighbor only for display",
                            "scalar_scale": "fixed 0..1 grayscale for reference, prediction, absolute error",
                            "mask_rgb": MASK_RGB,
                            "columns": ["original RGBA", "sanitized reference", "raw prediction", "absolute error"],
                            "metal_type": "fixed labels.json index palette; error is binary incorrect/correct, not numeric absolute difference",
                            "metal_palette_rgb": {label: PALETTE[i % len(PALETTE)] for i, label in enumerate(labels["metals"])}},
              "inputs": {"weights": _file_identity(weights, EXPECTED_WEIGHT_HASH),
                         "validation_jsonl": _file_identity(manifest, run["input_sha256"]["validation_manifest"]),
                         "labels": _file_identity(labels_path, run["input_sha256"]["labels"]),
                         "training_run_manifest": _file_identity(weights.parent / "run-manifest.json"),
                         "code": code},
              "selection": {"excluded_item": {"sample_id": DOOR_ITEM_ID, "reference_entry": DOOR_ITEM_ENTRY},
                            "selected_block_halves": door_pair,
                            "reason": "The item is a held icon; placed upper and lower block textures determine the detailed PBR visual review."},
              "door_pair": door_pair, "door_preview": door_preview,
              "annotation_note": "annotation-note.json",
              "usage_contract": {"schema_version": usage_contract["schema_version"],
                                 "identity": _file_identity(DEFAULT_CONTRACT),
                                 "caveat": "Usage guidance is not a model prediction or reviewed pixel supervision."},
              "device": str(device), "samples": samples, "pooled": totals, "sheets": sheets}
    report_path = output / "diagnostic-report.json"
    report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False, allow_nan=False) + "\n", "utf-8")
    return {"status": "diagnosis_complete", "output": str(output.resolve()),
            "report": str(report_path.resolve()), "sample_count": len(samples), "sheets": sheets}

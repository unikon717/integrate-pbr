"""Human review packets for sparse reference supervision."""

from __future__ import annotations

import hashlib
import base64
import json
import random
import re
import shutil
import tempfile
from collections import defaultdict
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

from .dataset import ReviewedTextureDataset


REPO = Path(__file__).resolve().parents[3]
LABELS = json.loads((REPO / "contracts" / "labels.json").read_text("utf-8"))
SEMANTIC = ("material", "structure", "boundary_x", "boundary_y", "fine_depth")
DOORS = {"ref-868e4a00cceb8e26-442802c1a6": "assets/minecraft/textures/block/birch_door_top.png",
         "ref-932705109984973e-35a7bfcc94": "assets/minecraft/textures/block/birch_door_bottom.png"}
DOOR_MATERIALS = {name: LABELS["materials"].index(name) for name in ("wood", "metal")}
DOOR_STRUCTURES = {name: LABELS["structures"].index(name) for name in ("border", "inset_panel", "fitting")}
SAFE_ID = re.compile(r"^[A-Za-z0-9_.:-]+$")


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _rows(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text("utf-8").splitlines() if line.strip()]


def _contained(root: Path, relative: str) -> Path:
    if not isinstance(relative, str) or Path(relative).is_absolute():
        raise ValueError(f"unsafe dataset path: {relative}")
    path = (root / relative).resolve()
    if root.resolve() not in path.parents:
        raise ValueError(f"unsafe dataset path: {relative}")
    return path


def _door_packet(packet: Path, sample_id: str | None = None):
    index = json.loads((packet / "index.json").read_text("utf-8"))
    if index.get("schema_version") != 1 or index.get("labels_sha256") != _sha(REPO / "contracts/labels.json"):
        raise ValueError("packet schema or label vocabulary changed")
    selected = index.get("selected")
    if not isinstance(selected, list):
        raise ValueError("invalid selected rows")
    matches = {}
    for entry in selected:
        sid = entry.get("sample_id")
        if sid in DOORS:
            if entry.get("reference_entry") != DOORS[sid] or sid in matches:
                raise ValueError("door identity pair mismatch")
            matches[sid] = entry
    if sample_id is not None and sample_id not in matches:
        raise ValueError("exact selected door identity pair absent")
    return index, matches


def _door_source(packet: Path, index: dict, entry: dict):
    sid = entry["sample_id"]
    if not SAFE_ID.fullmatch(sid):
        raise ValueError("unsafe sample ID")
    source = _contained(packet, f"sources/{sid}.png")
    measured = _contained(packet, f"measured_targets/{sid}.npz")
    if _sha(source) != entry.get("source_png_sha256"):
        raise ValueError("source PNG hash changed")
    with Image.open(source) as opened:
        rgba = np.asarray(opened.convert("RGBA"), dtype=np.uint8)
    if (hashlib.sha256(rgba.tobytes()).hexdigest() != entry.get("decoded_rgba_sha256") or
            (rgba.shape[1], rgba.shape[0]) != (entry.get("width"), entry.get("height"))):
        raise ValueError("decoded source changed")
    with np.load(measured, allow_pickle=False) as npz:
        if "metal_type" not in npz.files:
            raise ValueError("measured metal missing")
        metal = np.array(npz["metal_type"])
    if metal.shape != rgba.shape[:2]:
        raise ValueError("measured metal shape changed")
    original = _contained(Path(index["dataset_root"]), entry["targets"])
    if _sha(original) != entry.get("target_npz_sha256"):
        raise ValueError("source target measurements changed")
    with np.load(original, allow_pickle=False) as npz:
        if "metal_type" not in npz.files or not np.array_equal(metal, npz["metal_type"], equal_nan=True):
            raise ValueError("measured target changed")
    evidence = np.isfinite(metal) & (metal != 0) & (metal != 255) & (rgba[:, :, 3] > 0)
    return source, rgba, evidence


def _audit(training_root: Path, rows: list[dict]) -> tuple[list[dict], list[dict]]:
    manifests = sorted(training_root.glob("*/train.jsonl"))
    if not manifests:
        raise ValueError("no train manifests to audit")
    keys: dict[str, dict[str, set[str]]] = {
        "source_artwork_id": defaultdict(set), "derivative_group": defaultdict(set)}
    recorded = []
    for path in manifests:
        training = _rows(path)
        recorded.append({"path": str(path.resolve()), "sha256": _sha(path),
                         "sample_count": len(training)})
        for row in training:
            for field in keys:
                if row.get(field):
                    keys[field][row[field]].add(str(path.resolve()))
    collisions = []
    for row in rows:
        hit = {field: {"value": row[field], "manifests": sorted(keys[field][row[field]])}
               for field in keys if row.get(field) and row[field] in keys[field]}
        collisions.append({"sample_id": row["sample_id"],
                           "lineage": "known_lineage_overlap" if hit else "known_lineage_nonoverlap",
                           "collisions": hit})
    return recorded, collisions


def _category(row: dict, alpha: np.ndarray) -> list[str]:
    name = row.get("name", "").lower()
    family = row.get("material_family", "").lower()
    found = []
    if "wood" in name and any(x in name for x in ("axe", "pickaxe", "shovel", "hoe", "sword")):
        found.append("wood-only tool candidate")
    if any(x in name for x in ("axe", "pickaxe", "shovel", "hoe", "sword")):
        found.append("mixed wood/metal tool candidate")
    if "door" in name:
        found.append("door/trapdoor candidate")
    if "log" in name and any(x in name for x in ("top", "end")):
        found.append("log end candidate")
    if "plank" in name:
        found.append("planks candidate")
    if family == "masonry":
        found.append("masonry candidate")
    if "brick" in name:
        found.append("brick candidate")
    if family == "metal" and "/item/" in row.get("reference_entry", ""):
        found.append("metal item candidate")
    if np.any(alpha < 255):
        found.append("transparent source")
    # Tiny fittings require pixel review; a filename cannot locate them.
    return found


def _render(source: Path, maps: dict[str, np.ndarray], destination: Path,
            *, diagnostic: bool) -> None:
    with Image.open(source) as opened:
        color = opened.convert("RGBA")
    panels = [color]
    for key in ("base_depth", "smoothness", "metal_type"):
        values = maps[key]
        if key == "metal_type":
            gray = np.where(values == 255, 0, np.where(values > 0, 255, 80)).astype(np.uint8)
        else:
            gray = (np.nan_to_num(values, nan=0.0).clip(0, 1) * 255).astype(np.uint8)
        panels.append(Image.fromarray(gray, "L").convert("RGBA"))
    scale = max(1, min(8, 128 // max(color.size)))
    width, height = color.size
    result = Image.new("RGB", (width * scale * 4, height * scale + 28), "#202020")
    draw = ImageDraw.Draw(result)
    for i, panel in enumerate(panels):
        result.paste(panel.resize((width * scale, height * scale), Image.Resampling.NEAREST),
                     (i * width * scale, 28), panel.resize((width * scale, height * scale), Image.Resampling.NEAREST))
    draw.text((3, 3), "SOURCE | measured depth | measured smooth | measured metal", fill="white")
    if diagnostic:
        draw.text((3, 15), "OVERLAP DIAGNOSTIC", fill="#ff8888")
    if scale >= 4:
        for x in range(width + 1):
            draw.line((x * scale, 28, x * scale, 28 + height * scale), fill="#555555")
        for y in range(height + 1):
            draw.line((0, 28 + y * scale, width * scale, 28 + y * scale), fill="#555555")
    result.save(destination)


def review_packet(dataset_root: Path, manifest: Path, training_root: Path, output: Path,
                  *, limit: int = 16, seed: int = 20260930) -> dict:
    if output.exists():
        raise FileExistsError(output)
    if limit < 1:
        raise ValueError("limit must be positive")
    rows = _rows(manifest)
    ids = [row.get("sample_id") for row in rows]
    if len(ids) != len(set(ids)) or any(not isinstance(i, str) or not SAFE_ID.fullmatch(i) for i in ids):
        raise ValueError("invalid or duplicate sample IDs")
    dataset = ReviewedTextureDataset(dataset_root, manifest,
                                     material_classes=len(LABELS["materials"]),
                                     structure_classes=len(LABELS["structures"]),
                                     object_classes=len(LABELS["objects"]),
                                     metal_classes=len(LABELS["metals"]))
    training, collisions = _audit(training_root, rows)
    inspected = []
    for i, (row, collision) in enumerate(zip(rows, collisions)):
        source = _contained(dataset_root, row["source"])
        _contained(dataset_root, row["targets"])
        sample = dataset[i]
        with Image.open(source) as opened:
            rgba = np.asarray(opened.convert("RGBA"), dtype=np.uint8)
        record = {**collision, "source": row["source"], "targets": row["targets"],
                  "source_png_sha256": _sha(source),
                  "target_npz_sha256": _sha(_contained(dataset_root, row["targets"])),
                  "decoded_rgba_sha256": hashlib.sha256(rgba.tobytes()).hexdigest(),
                  "width": rgba.shape[1], "height": rgba.shape[0],
                  "name_candidate": row.get("name"),
                  "candidate_object_type": row.get("candidate_object_type"),
                  "candidate_base_material": row.get("candidate_base_material"),
                  "source_artwork_id": row["source_artwork_id"],
                  "derivative_group": row["derivative_group"],
                  "material_family": row.get("material_family"),
                  "style_family": row.get("style_family"),
                  "reference_pack": row.get("reference_pack"),
                  "reference_pack_sha256": row.get("reference_pack_sha256"),
                  "reference_entry": row.get("reference_entry"),
                  "categories": _category(row, rgba[:, :, 3]), "row": row,
                  "maps": {k: v.numpy() for k, v in sample["targets"].items()}}
        inspected.append(record)
    eligible = [x for x in inspected if x["lineage"] == "known_lineage_nonoverlap"]
    overlapping = [x for x in inspected if x["lineage"] == "known_lineage_overlap"]
    rng = random.Random(seed)
    rng.shuffle(eligible)
    buckets = defaultdict(list)
    for item in eligible:
        buckets[(item["material_family"], (item["name_candidate"] or "").split(" ")[0])].append(item)
    selected = []
    while buckets and len(selected) < limit:
        for key in sorted(list(buckets)):
            if len(selected) >= limit:
                break
            selected.append(buckets[key].pop())
            if not buckets[key]:
                del buckets[key]
    diagnostics = sorted(overlapping, key=lambda x: x["sample_id"])[:4]
    category_names = ("wood-only tool candidate", "mixed wood/metal tool candidate",
                      "door/trapdoor candidate", "log end candidate", "planks candidate",
                      "masonry candidate", "brick candidate", "metal item candidate",
                      "transparent source", "tiny fittings unknown until visual review")
    coverage = {name: {"eligible": sum(name in x["categories"] for x in eligible),
                       "overlap": sum(name in x["categories"] for x in overlapping),
                       "unknown": sum(name not in x["categories"] for x in inspected)}
                for name in category_names}
    try:
        output.mkdir(parents=True)
        for subdir in ("drafts", "previews", "sources", "measured_targets"):
            (output / subdir).mkdir()
        index = {"schema_version": 1, "dataset_root": str(dataset_root.resolve()),
                 "labels_sha256": _sha(REPO / "contracts" / "labels.json"),
                 "validation_manifest": str(manifest.resolve()),
                 "validation_manifest_sha256": _sha(manifest),
                 "training_root": str(training_root.resolve()), "training_manifests": training,
                 "selected": [], "overlap_diagnostics": [],
                 "lineage_statement": "known_lineage_nonoverlap; checkpoint_lineage_unverified"}
        for item, diagnostic in [(x, False) for x in selected] + [(x, True) for x in diagnostics]:
            entry = {k: v for k, v in item.items() if k not in ("row", "maps")}
            field = "overlap_diagnostics" if diagnostic else "selected"
            index[field].append(entry)
            preview = output / "previews" / f"{item['sample_id']}.png"
            _render(_contained(dataset_root, item["source"]), item["maps"], preview,
                    diagnostic=diagnostic)
            if not diagnostic:
                shutil.copyfile(_contained(dataset_root, item["source"]),
                                output / "sources" / f"{item['sample_id']}.png")
                np.savez_compressed(output / "measured_targets" / f"{item['sample_id']}.npz",
                                    **item["maps"])
                draft = {"sample_id": item["sample_id"], "review_status": "pending",
                         "reviewer": None, "review_date": None,
                         "annotation_version": None, "evidence": "",
                         "unresolved_questions": "", "object_type": None,
                         "object_materials": [None] * len(LABELS["materials"]),
                         "source_png_sha256": item["source_png_sha256"],
                         "decoded_rgba_sha256": item["decoded_rgba_sha256"],
                         "width": item["width"], "height": item["height"],
                         "base_provenance": item["row"].get("target_provenance", {})}
                (output / "drafts" / f"{item['sample_id']}.json").write_text(
                    json.dumps(draft, indent=2) + "\n", "utf-8")
                shape = (item["height"], item["width"])
                np.savez_compressed(output / "drafts" / f"{item['sample_id']}.npz",
                                    material=np.full(shape, 255, dtype=np.float32),
                                    structure=np.full(shape, 255, dtype=np.float32),
                                    boundary_x=np.full(shape, np.nan, dtype=np.float32),
                                    boundary_y=np.full(shape, np.nan, dtype=np.float32),
                                    fine_depth=np.full(shape, np.nan, dtype=np.float32))
        previews = [Image.open(output / "previews" / f"{x['sample_id']}.png").convert("RGB")
                    for x in selected + diagnostics]
        if previews:
            w, h = max(x.width for x in previews), max(x.height for x in previews)
            sheet = Image.new("RGB", (w * 2, h * ((len(previews) + 1) // 2)), "#202020")
            for i, preview in enumerate(previews):
                sheet.paste(preview, ((i % 2) * w, (i // 2) * h))
            sheet.save(output / "contact-sheet.png")
        else:
            Image.new("RGB", (1, 1), "#202020").save(output / "contact-sheet.png")
        audit = {"input_hashes": {"validation_manifest": _sha(manifest),
                                   "train_manifests": training},
                 "validation_samples": len(rows), "eligible": len(eligible),
                 "known_lineage_overlap": len(overlapping), "selected": len(selected),
                 "selection_deficit": max(0, limit - len(selected)),
                 "overlap_diagnostics": len(diagnostics), "coverage": coverage,
                 "selection_algorithm": "seeded shuffle, round-robin material-family/name-first-token buckets",
                 "seed": seed, "collisions": collisions,
                 "limitations": ["checkpoint_lineage_unverified", "same mod/reference pack",
                                 "candidate categories are not labels"]}
        (output / "index.json").write_text(json.dumps(index, indent=2) + "\n", "utf-8")
        (output / "audit.json").write_text(json.dumps(audit, indent=2) + "\n", "utf-8")
        return audit
    except Exception:
        shutil.rmtree(output)
        raise


def import_review(packet: Path, training_root: Path, output: Path) -> dict:
    if output.exists():
        raise FileExistsError(output)
    index = json.loads((packet / "index.json").read_text("utf-8"))
    if index.get("labels_sha256") != _sha(REPO / "contracts" / "labels.json"):
        raise ValueError("label vocabulary changed")
    if Path(index["training_root"]).resolve() != training_root.resolve():
        raise ValueError("training root differs from packet")
    manifest = Path(index["validation_manifest"])
    dataset_root = Path(index["dataset_root"])
    if _sha(manifest) != index["validation_manifest_sha256"]:
        raise ValueError("validation manifest changed")
    rows = _rows(manifest)
    current_train, collisions = _audit(training_root, rows)
    if current_train != index["training_manifests"]:
        raise ValueError("training manifest lineage changed")
    collision_by_id = {x["sample_id"]: x for x in collisions}
    rows_by_id = {x["sample_id"]: x for x in rows}
    selected = index["selected"]
    ids = [x["sample_id"] for x in selected]
    if len(ids) != len(set(ids)) or any(not SAFE_ID.fullmatch(i) for i in ids):
        raise ValueError("invalid or duplicate sample IDs")
    dataset = ReviewedTextureDataset(dataset_root, manifest,
                                     material_classes=len(LABELS["materials"]),
                                     structure_classes=len(LABELS["structures"]),
                                     object_classes=len(LABELS["objects"]),
                                     metal_classes=len(LABELS["metals"]))
    sample_by_id = {row["sample_id"]: dataset[i] for i, row in enumerate(rows)}
    approved = []
    for entry in selected:
        sample_id = entry["sample_id"]
        if entry["lineage"] != "known_lineage_nonoverlap" or collision_by_id[sample_id]["lineage"] != "known_lineage_nonoverlap":
            raise ValueError("overlap cannot be imported")
        draft_path = _contained(packet, f"drafts/{sample_id}.json")
        draft = json.loads(draft_path.read_text("utf-8"))
        if draft.get("review_status") == "pending":
            continue
        if draft.get("review_status") != "approved" or not str(draft.get("reviewer") or "").strip():
            raise ValueError("approved review requires a reviewer")
        if (not str(draft.get("review_date") or "").strip() or
                type(draft.get("annotation_version")) is not int or
                draft["annotation_version"] < 1):
            raise ValueError("approved review requires date and annotation version")
        source = _contained(dataset_root, rows_by_id[sample_id]["source"])
        target = _contained(dataset_root, rows_by_id[sample_id]["targets"])
        if _sha(target) != entry.get("target_npz_sha256"):
            raise ValueError("source target measurements changed")
        with Image.open(source) as opened:
            rgba = np.asarray(opened.convert("RGBA"), dtype=np.uint8)
        if (_sha(source) != entry["source_png_sha256"] or
                hashlib.sha256(rgba.tobytes()).hexdigest() != entry["decoded_rgba_sha256"] or
                (rgba.shape[1], rgba.shape[0]) != (entry["width"], entry["height"]) or
                any(draft.get(k) != entry[k] for k in ("sample_id", "source_png_sha256",
                                                    "decoded_rgba_sha256", "width", "height"))):
            raise ValueError("source integrity changed")
        object_type = draft.get("object_type")
        if object_type is not None and (type(object_type) is not int or
                                        not 0 <= object_type < len(LABELS["objects"])):
            raise ValueError("invalid object_type")
        materials = draft.get("object_materials")
        if not isinstance(materials, list) or len(materials) != len(LABELS["materials"]) or any(
                type(x) is not int and x is not None or x not in (0, 1, None) for x in materials):
            raise ValueError("invalid object_materials")
        with np.load(_contained(packet, f"drafts/{sample_id}.npz"), allow_pickle=False) as npz:
            if set(npz.files) != set(SEMANTIC):
                raise ValueError("invalid semantic NPZ keys")
            overlays = {k: np.array(npz[k], dtype=np.float32) for k in SEMANTIC}
        shape = rgba.shape[:2]
        for key, values in overlays.items():
            if values.shape != shape:
                raise ValueError(f"invalid {key} shape")
            if key in ("material", "structure"):
                count = len(LABELS["materials" if key == "material" else "structures"])
                if not np.all(np.isfinite(values)) or np.any((values != 255) &
                        ((values < 0) | (values >= count) | (values != np.floor(values)))):
                    raise ValueError(f"invalid {key} labels")
            elif np.any(np.isfinite(values) & ((values < 0) | (values > 1))):
                raise ValueError(f"invalid {key} values")
        observed_materials = sample_by_id[sample_id]["object_materials"].tolist()
        combined_materials = [reviewed if reviewed is not None else
                              (int(observed) if np.isfinite(observed) else None)
                              for reviewed, observed in zip(materials, observed_materials)]
        metal_index = LABELS["materials"].index("metal")
        if observed_materials[metal_index] == 1 and materials[metal_index] == 0:
            raise ValueError("reviewed metal negative contradicts observed metal code")
        if not (object_type is not None or any(x is not None for x in materials) or
                np.any(overlays["material"] != 255) or np.any(overlays["structure"] != 255) or
                np.any(np.isfinite(overlays["boundary_x"])) or
                np.any(np.isfinite(overlays["boundary_y"]))):
            raise ValueError("approval needs a known semantic value")
        approved.append((entry, draft, overlays, rgba, sample_by_id[sample_id],
                         combined_materials))
    if not approved:
        raise ValueError("no approved reviews")
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=output.name + ".tmp-", dir=output.parent))
    try:
        out_rows = []
        for entry, draft, overlays, rgba, sample, combined_materials in approved:
            sample_id = entry["sample_id"]
            source_rel = f"sources/{sample_id}.png"
            target_rel = f"targets/{sample_id}.npz"
            (temporary / "sources").mkdir(exist_ok=True)
            (temporary / "targets").mkdir(exist_ok=True)
            shutil.copyfile(_contained(dataset_root, entry["source"]), temporary / source_rel)
            maps = {k: v.numpy().copy() for k, v in sample["targets"].items()}
            for key, values in overlays.items():
                known = values != 255 if key in ("material", "structure") else np.isfinite(values)
                maps[key][known] = values[known]
            np.savez_compressed(temporary / target_rel, **maps)
            row = dict(rows_by_id[sample_id])
            provenance = dict(row.get("target_provenance", {}))
            for key, values in overlays.items():
                known = values != 255 if key in ("material", "structure") else np.isfinite(values)
                if np.any(known):
                    provenance[key] = "human_reviewed"
            if draft["object_type"] is not None:
                provenance["object_type"] = "human_reviewed"
            if any(x is not None for x in draft["object_materials"]):
                provenance["object_materials"] = "human_reviewed_partial"
            row.update(source=source_rel, targets=target_rel, reviewed=True,
                       reviewer=draft["reviewer"], object_type=draft["object_type"],
                       object_materials=combined_materials,
                       review_date=draft["review_date"], evidence=draft.get("evidence", ""),
                       unresolved_questions=draft.get("unresolved_questions", ""),
                       annotation_version=draft["annotation_version"],
                       supervision_source="reviewed_reference_pbr_pair",
                       target_provenance=provenance)
            out_rows.append(row)
        out_manifest = temporary / "train.jsonl"
        out_manifest.write_text("".join(json.dumps(r) + "\n" for r in out_rows), "utf-8")
        validated = ReviewedTextureDataset(temporary, out_manifest,
                                           material_classes=len(LABELS["materials"]),
                                           structure_classes=len(LABELS["structures"]),
                                           object_classes=len(LABELS["objects"]),
                                           metal_classes=len(LABELS["metals"]))
        for i in range(len(validated)):
            validated[i]
        _, post_collision = _audit(training_root, out_rows)
        if any(x["lineage"] != "known_lineage_nonoverlap" for x in post_collision):
            raise ValueError("new training lineage collision")
        report = {"imported": len(out_rows), "lineage": "known_lineage_nonoverlap",
                  "checkpoint_lineage": "unverified", "source_packet": str(packet.resolve())}
        (temporary / "import-report.json").write_text(json.dumps(report, indent=2) + "\n", "utf-8")
        temporary.rename(output)
        return report
    except Exception:
        shutil.rmtree(temporary)
        raise

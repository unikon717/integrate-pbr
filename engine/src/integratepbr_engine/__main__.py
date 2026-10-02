"""Development CLI for training the compact material network."""

from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import importlib.metadata
import json
import platform
import random
from pathlib import Path
from .model_package import ARCHITECTURE, create_metadata, validate_package
from .preprocess import CURRENT_PREPROCESS_VERSION


def _manifest(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text("utf-8").splitlines() if line.strip()]


def _assert_disjoint(train_rows: list[dict], validation_rows: list[dict]) -> None:
    # Source art and all declared derivatives must stay on one side of the split.
    keys = ("source_artwork_id", "derivative_group")
    for key in keys:
        train_values = {row.get(key) for row in train_rows if row.get(key)}
        overlap = train_values.intersection(row.get(key) for row in validation_rows if row.get(key))
        if overlap:
            raise ValueError(f"train/validation leakage in {key}: {sorted(overlap)[:5]}")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _file_inventory(paths: list[Path], root: Path) -> dict:
    files = {path.relative_to(root).as_posix(): _sha256(path) for path in paths}
    aggregate = hashlib.sha256()
    for name, digest in sorted(files.items()):
        aggregate.update(f"{name}\t{digest}\n".encode("utf-8"))
    return {"files": files, "aggregate_sha256": aggregate.hexdigest(),
            "aggregate_rule": "SHA-256 of sorted UTF-8 path\\tSHA-256\\n records"}


def _effective_counts(dataset) -> dict:
    import torch
    result = {"manifest_rows": len(dataset), "supervision_source": dict(Counter(
        row.get("supervision_source", "reviewed_annotation") for row in dataset.rows)),
        "reviewed": dict(Counter("reviewed" if row.get("reviewed", False) else "unreviewed"
                                  for row in dataset.rows)),
        "effective_labels": {"object_type_samples": 0, "object_material_finite_tags": 0,
                             "object_material_positive_tags": 0}}
    counts = result["effective_labels"]
    for key in dataset.REQUIRED_TARGETS:
        counts[f"{key}_pixels"] = 0
    for index in range(len(dataset)):
        sample = dataset[index]
        valid = sample["image"][4] > 0.5
        counts["object_type_samples"] += int(sample["object_type"] != -100)
        finite = torch.isfinite(sample["object_materials"])
        counts["object_material_finite_tags"] += int(finite.sum())
        counts["object_material_positive_tags"] += int((finite &
            (sample["object_materials"] >= 0.5)).sum())
        for key, value in sample["targets"].items():
            mask = torch.isfinite(value)
            if key in ("material", "structure", "metal_type"):
                mask &= value != 255
            counts[f"{key}_pixels"] += int((valid & mask).sum())
    return result


def _train(args: argparse.Namespace) -> int:
    try:
        import numpy as np
        import PIL
        import safetensors
        import torch
        from torch.utils.data import DataLoader
        from integratepbr_engine.dataset import ReviewedTextureDataset, collate_native
        from integratepbr_engine.network import ContextSwinUNet
        from integratepbr_engine.training import fit
    except RuntimeError as exc:
        raise SystemExit(str(exc)) from exc

    if args.output.exists():
        raise ValueError(f"output directory already exists: {args.output}")
    for path in (args.dataset_root, args.train_manifest, args.validation_manifest, args.labels):
        if not path.exists():
            raise FileNotFoundError(path)
    if args.epochs < 1 or args.batch_size < 1 or args.learning_rate <= 0:
        raise ValueError("epochs, batch size and learning rate must be positive")
    train_rows = _manifest(args.train_manifest)
    validation_rows = _manifest(args.validation_manifest)
    _assert_disjoint(train_rows, validation_rows)
    labels = json.loads(args.labels.read_text("utf-8"))
    for key in ("materials", "structures", "objects", "metals"):
        if not isinstance(labels.get(key), list) or not labels[key] or len(set(labels[key])) != len(labels[key]):
            raise ValueError(f"invalid {key} label table")
    report_path = args.dataset_root / "dataset-report.json"
    if report_path.exists():
        report = json.loads(report_path.read_text("utf-8"))
        if (len(train_rows), len(validation_rows)) != (report["train_samples"], report["validation_samples"]):
            raise ValueError("manifest row counts disagree with dataset report")
    train_data = ReviewedTextureDataset(args.dataset_root, args.train_manifest,
                                        material_classes=len(labels["materials"]),
                                        structure_classes=len(labels["structures"]),
                                        object_classes=len(labels["objects"]),
                                        metal_classes=len(labels["metals"]))
    validation_data = ReviewedTextureDataset(args.dataset_root, args.validation_manifest,
                                             material_classes=len(labels["materials"]),
                                             structure_classes=len(labels["structures"]),
                                             object_classes=len(labels["objects"]),
                                             metal_classes=len(labels["metals"]))
    if not train_data or not validation_data:
        raise SystemExit("Training and validation manifests must both contain usable samples")
    train_counts = _effective_counts(train_data)
    validation_counts = _effective_counts(validation_data)
    if not any(value for key, value in validation_counts["effective_labels"].items()
               if key.endswith("_pixels") or key.endswith("_samples") or key.endswith("_tags")):
        raise ValueError("effective validation supervision is empty")
    root = args.dataset_root.resolve()
    asset_paths = sorted({dataset._resolve(row[key]) for dataset in (train_data, validation_data)
                          for row in dataset.rows for key in ("source", "targets")})
    assets = _file_inventory(asset_paths, root)
    repo = Path(__file__).resolve().parents[3]
    code_paths = [repo / "engine/src/integratepbr_engine" / name for name in
                  ("__main__.py", "dataset.py", "network.py", "training.py", "preprocess.py", "model_package.py")]
    code_paths.append(repo / "engine/pyproject.toml")
    code = _file_inventory(code_paths, repo)
    random.seed(args.seed)
    np.random.seed(args.seed)
    torch.manual_seed(args.seed)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(args.seed)
    generator = torch.Generator().manual_seed(args.seed)
    model = ContextSwinUNet(material_classes=len(labels["materials"]),
                            structure_classes=len(labels["structures"]),
                            object_classes=len(labels["objects"]),
                            metal_classes=len(labels["metals"]))
    if args.init_weights:
        try:
            from safetensors.torch import load_file
        except ImportError as exc:
            raise SystemExit("Warm-starting requires safetensors from the 'train' dependencies") from exc
        validate_package(args.init_weights, args.labels,
                         parameter_count=sum(p.numel() for p in model.parameters()))
        loaded = load_file(str(args.init_weights), device="cpu")
        model.load_state_dict(loaded, strict=True)
    device = torch.device("cuda" if torch.cuda.is_available() and not args.cpu else "cpu")
    common = {"batch_size": args.batch_size, "num_workers": 0, "collate_fn": collate_native}
    train_loader = DataLoader(train_data, shuffle=True, generator=generator, **common)
    validation_loader = DataLoader(validation_data, shuffle=False, **common)
    print(json.dumps({"device": str(device), "parameters": sum(p.numel() for p in model.parameters()),
                      "train_samples": len(train_data), "validation_samples": len(validation_data),
                      "batch_size": args.batch_size}, ensure_ascii=False), flush=True)
    started = datetime.now(timezone.utc).isoformat()
    result = fit(model, train_loader, validation_loader, epochs=args.epochs,
                 learning_rate=args.learning_rate, device=device,
                 output_dir=args.output.resolve(), seed=args.seed)
    weight_path = args.output / "model.safetensors"
    weight_hash = _sha256(weight_path)
    metadata_path = args.output / "model-metadata.json"
    metadata = json.loads(metadata_path.read_text("utf-8"))
    reserved = {"package_schema_version", "architecture", "preprocessing_version", "labels_sha256",
                "weights_file", "weights_sha256", "parameter_count"}
    metadata = {key: value for key, value in metadata.items() if key not in reserved}
    metadata = create_metadata(weight_path, args.labels,
                               sum(p.numel() for p in model.parameters()),
                               **{**metadata, "run_manifest": "run-manifest.json"})
    metadata_path.write_text(json.dumps(metadata, indent=2) + "\n", "utf-8")
    manifest = {
        "scope": "same-source development validation",
        "paths": {"dataset_root": str(root), "train_manifest": str(args.train_manifest.resolve()),
                  "validation_manifest": str(args.validation_manifest.resolve()),
                  "labels": str(args.labels.resolve()), "output": str(args.output.resolve())},
        "started_utc": started, "completed_utc": datetime.now(timezone.utc).isoformat(),
        "input_sha256": {"train_manifest": _sha256(args.train_manifest),
                         "validation_manifest": _sha256(args.validation_manifest),
                         "labels": _sha256(args.labels), "assets": assets},
        "code_sha256": code,
        "environment": {"python": platform.python_version(), "platform": platform.platform(),
                        "numpy": np.__version__, "pillow": PIL.__version__,
                        "torch": torch.__version__, "safetensors": importlib.metadata.version("safetensors"),
                        "cuda_runtime": torch.version.cuda, "cuda_available": torch.cuda.is_available(),
                        "gpu": torch.cuda.get_device_name(0) if torch.cuda.is_available() else None,
                        "device": str(device)},
        "determinism": {"seed": args.seed, "python_numpy_torch_cpu_cuda_seeded_before_model_init": True,
                        "data_loader_generator_seeded": True, "torch_deterministic_algorithms":
                        torch.are_deterministic_algorithms_enabled(),
                        "cudnn_deterministic": torch.backends.cudnn.deterministic,
                        "cudnn_benchmark": torch.backends.cudnn.benchmark,
                        "gpu_note": "Seeded GPU execution is not guaranteed bit-identical across runs, drivers, or devices."},
        "training": {"initialization": str(args.init_weights.resolve()) if args.init_weights else "random from scratch; no checkpoint loaded",
                     "architecture": ARCHITECTURE, "preprocessing_version": CURRENT_PREPROCESS_VERSION,
                     "parameter_count": sum(p.numel() for p in model.parameters()),
                     "requested_epochs": args.epochs, "completed_epochs": result["completed_epochs"],
                     "batch_size": args.batch_size, "learning_rate": args.learning_rate,
                     "weight_decay": result["weight_decay"],
                     "early_stop_patience": result["early_stop_patience"],
                     "scheduler_patience": result["scheduler_patience"],
                     "best_epoch": result["best_epoch"],
                     "best_validation_loss": result["best_validation_loss"]},
        "effective_supervision": {"train": train_counts, "validation": validation_counts},
        "model": {"file": "model.safetensors", "sha256": weight_hash,
                  "bytes": weight_path.stat().st_size}}
    (args.output / "run-manifest.json").write_text(json.dumps(manifest, indent=2,
        ensure_ascii=False) + "\n", "utf-8")
    print(json.dumps({"status": "training_complete", **result}, ensure_ascii=False), flush=True)
    return 0


def _prepare_reference(args: argparse.Namespace) -> int:
    try:
        from integratepbr_engine.dataset import prepare_reference_seed
    except RuntimeError as exc:
        raise SystemExit(str(exc)) from exc
    if args.limit < 4:
        raise SystemExit("--limit must be at least 4 to create disjoint train/validation sets")
    labels = json.loads(args.labels.read_text("utf-8"))
    report = prepare_reference_seed(args.reference_dir, args.output, labels,
                                    limit=args.limit, seed=args.seed)
    print(json.dumps({"status": "dataset_prepared", "output": str(args.output.resolve()),
                      **report}, ensure_ascii=False, indent=2), flush=True)
    return 0


def _review_packet(args: argparse.Namespace) -> int:
    from integratepbr_engine.review import review_packet
    result = review_packet(args.dataset_root, args.manifest, args.training_root,
                           args.output, limit=args.limit, seed=args.seed)
    print(json.dumps(result, ensure_ascii=False, indent=2), flush=True)
    return 0


def _import_review(args: argparse.Namespace) -> int:
    from integratepbr_engine.review import import_review
    result = import_review(args.packet, args.training_root, args.output)
    print(json.dumps(result, ensure_ascii=False, indent=2), flush=True)
    return 0


def _evaluate(args: argparse.Namespace) -> int:
    try:
        import torch
        from safetensors.torch import load_file
        from torch.utils.data import DataLoader
        from integratepbr_engine.dataset import ReviewedTextureDataset, collate_native
        from integratepbr_engine.network import (ContextSwinUNet,
                                                  constrained_metal_probabilities)
    except RuntimeError as exc:
        raise SystemExit(str(exc)) from exc
    except ImportError as exc:
        raise SystemExit("Evaluation requires the optional 'train' dependencies") from exc

    labels = json.loads(args.labels.read_text("utf-8"))
    dataset = ReviewedTextureDataset(
        args.dataset_root, args.manifest,
        material_classes=len(labels["materials"]),
        structure_classes=len(labels["structures"]),
        object_classes=len(labels["objects"]),
        metal_classes=len(labels["metals"]))
    if not dataset:
        raise SystemExit("The evaluation manifest is empty")
    device = torch.device("cuda" if torch.cuda.is_available() and not args.cpu else "cpu")
    model = ContextSwinUNet(
        material_classes=len(labels["materials"]),
        structure_classes=len(labels["structures"]),
        object_classes=len(labels["objects"]),
        metal_classes=len(labels["metals"]))
    validate_package(args.weights, args.labels,
                     parameter_count=sum(p.numel() for p in model.parameters()))
    model.load_state_dict(load_file(str(args.weights), device="cpu"), strict=True)
    model.to(device).eval()
    loader = DataLoader(dataset, batch_size=args.batch_size, shuffle=False,
                        num_workers=0, collate_fn=collate_native)
    scalar_names = ("base_depth", "fine_depth", "smoothness", "dielectric_f0", "ao")
    scalar_sums = {name: 0.0 for name in scalar_names}
    scalar_counts = {name: 0 for name in scalar_names}
    material_correct = material_count = object_correct = object_count = 0
    object_material_correct = object_material_count = 0
    object_material_classes = len(labels["materials"])
    object_material_tp = torch.zeros(object_material_classes, dtype=torch.int64)
    object_material_fp = torch.zeros(object_material_classes, dtype=torch.int64)
    object_material_fn = torch.zeros(object_material_classes, dtype=torch.int64)
    metal_count = len(labels["metals"])
    metal_confusion_raw = torch.zeros(metal_count, metal_count, dtype=torch.int64)
    metal_confusion_constrained = torch.zeros(metal_count, metal_count, dtype=torch.int64)
    wooden_tool_samples = wooden_tool_pixels = 0
    wooden_tool_raw_metal_pixels = wooden_tool_constrained_metal_pixels = 0
    wooden_tool_details: list[dict[str, object]] = []
    wood_material_index = labels["materials"].index("wood")
    metal_material_index = labels["materials"].index("metal")
    tool_type_index = labels["objects"].index("tool")
    boundary_tp = boundary_fp = boundary_fn = 0
    boundary_count = structure_count = 0
    boundary_axis_counts = {"boundary_x": 0, "boundary_y": 0}
    provenance_counts: dict[str, int] = {}
    reviewed_counts = {"reviewed": 0, "unreviewed": 0}

    with torch.inference_mode():
        for batch in loader:
            for source, reviewed in zip(batch["supervision_source"], batch["reviewed"]):
                provenance_counts[source] = provenance_counts.get(source, 0) + 1
                reviewed_counts["reviewed" if reviewed else "unreviewed"] += 1
            batch = {key: (value.to(device) if torch.is_tensor(value) else
                           {name: item.to(device) if torch.is_tensor(item) else item
                            for name, item in value.items()} if isinstance(value, dict) else value)
                     for key, value in batch.items()}
            prediction = model(batch["image"], batch["metadata"], batch["name_bytes"])
            valid = batch["valid"][:, 0] > 0.5
            targets = batch["targets"]
            for name, output in (("base_depth", prediction.base_depth[:, 0]),
                                 ("fine_depth", prediction.fine_depth[:, 0]),
                                 ("smoothness", prediction.smoothness[:, 0]),
                                 ("dielectric_f0", prediction.dielectric_f0[:, 0]),
                                 ("ao", prediction.ao[:, 0])):
                mask = valid & torch.isfinite(targets[name])
                scalar_sums[name] += float((output - targets[name]).abs()[mask].sum())
                scalar_counts[name] += int(mask.sum())

            target_material = targets["material"].long()
            material_mask = valid & (target_material != 255)
            material_correct += int(((prediction.material.argmax(1) == target_material) &
                                     material_mask).sum())
            material_count += int(material_mask.sum())
            structure_count += int((valid & (targets["structure"] != 255)).sum())

            target_metal = targets["metal_type"].long()
            metal_mask = valid & (target_metal != 255)
            metal_true = target_metal[metal_mask].cpu()
            metal_predicted_raw = prediction.metal_type.argmax(1)[metal_mask].cpu()
            metal_confusion_raw += torch.bincount(
                metal_true * metal_count + metal_predicted_raw,
                minlength=metal_count * metal_count).reshape(metal_count, metal_count)
            constrained = constrained_metal_probabilities(
                prediction, metal_material_index=metal_material_index)
            metal_predicted_constrained = constrained.argmax(1)[metal_mask].cpu()
            metal_confusion_constrained += torch.bincount(
                metal_true * metal_count + metal_predicted_constrained,
                minlength=metal_count * metal_count).reshape(metal_count, metal_count)

            object_mask = batch["object_type"] != -100
            object_correct += int((prediction.object_type.argmax(1)[object_mask] ==
                                   batch["object_type"][object_mask]).sum())
            object_count += int(object_mask.sum())

            object_material_target = batch["object_materials"]
            object_material_mask = torch.isfinite(object_material_target)
            object_material_prediction = prediction.object_materials.sigmoid() >= 0.5
            object_material_truth = object_material_target >= 0.5
            object_material_correct += int(((object_material_prediction == object_material_truth) &
                                            object_material_mask).sum())
            object_material_count += int(object_material_mask.sum())
            object_material_tp += ((object_material_prediction & object_material_truth) &
                                   object_material_mask).sum(0).cpu().to(torch.int64)
            object_material_fp += ((object_material_prediction & ~object_material_truth) &
                                   object_material_mask).sum(0).cpu().to(torch.int64)
            object_material_fn += ((~object_material_prediction & object_material_truth) &
                                   object_material_mask).sum(0).cpu().to(torch.int64)

            composition = batch["object_materials"]
            wood_only_tool = ((batch["object_type"] == tool_type_index) &
                              torch.isfinite(composition[:, wood_material_index]) &
                              torch.isfinite(composition[:, metal_material_index]) &
                              (composition[:, wood_material_index] >= 0.5) &
                              (composition[:, metal_material_index] < 0.5))
            if wood_only_tool.any():
                wood_tool_mask = valid & wood_only_tool[:, None, None]
                wooden_tool_samples += int(wood_only_tool.sum())
                wooden_tool_pixels += int(wood_tool_mask.sum())
                raw_metal_probability = prediction.metal_type.softmax(1)[:, 1:].sum(1)
                constrained_metal_probability = constrained[:, 1:].sum(1)
                wooden_tool_raw_metal_pixels += int(
                    ((raw_metal_probability >= 0.5) & wood_tool_mask).sum())
                wooden_tool_constrained_metal_pixels += int(
                    ((constrained_metal_probability >= 0.5) & wood_tool_mask).sum())
                for sample_index in torch.where(wood_only_tool)[0].tolist():
                    pixel_mask = valid[sample_index]
                    pixel_count = int(pixel_mask.sum())
                    row = next(item for item in dataset.rows
                               if item["sample_id"] == batch["sample_id"][sample_index])
                    predicted_type = int(prediction.object_type[sample_index].argmax())
                    wooden_tool_details.append({
                        "name": row["name"],
                        "predicted_object_type": labels["objects"][predicted_type],
                        "object_wood_probability": float(
                            prediction.object_materials[sample_index, wood_material_index].sigmoid()),
                        "object_metal_probability": float(
                            prediction.object_materials[sample_index, metal_material_index].sigmoid()),
                        "raw_metal_pixel_rate": float(
                            ((raw_metal_probability[sample_index] >= 0.5) & pixel_mask).sum() /
                            max(1, pixel_count)),
                        "constrained_metal_pixel_rate": float(
                            ((constrained_metal_probability[sample_index] >= 0.5) & pixel_mask).sum() /
                            max(1, pixel_count)),
                    })

            boundary_target = torch.stack((targets["boundary_x"], targets["boundary_y"]), dim=1)
            boundary_mask = valid[:, None] & torch.isfinite(boundary_target)
            boundary_count += int(boundary_mask.sum())
            for axis in boundary_axis_counts:
                boundary_axis_counts[axis] += int((valid & torch.isfinite(targets[axis])).sum())
            boundary_prediction = prediction.boundary.sigmoid() >= 0.5
            boundary_truth = boundary_target >= 0.5
            boundary_tp += int((boundary_prediction & boundary_truth & boundary_mask).sum())
            boundary_fp += int((boundary_prediction & ~boundary_truth & boundary_mask).sum())
            boundary_fn += int((~boundary_prediction & boundary_truth & boundary_mask).sum())

    def metal_metrics(confusion: torch.Tensor) -> dict[str, object]:
        result = {}
        for index, name in enumerate(labels["metals"]):
            support = int(confusion[index].sum())
            predicted = int(confusion[:, index].sum())
            result[name] = {
                "support": support,
                "precision": float(confusion[index, index] / predicted) if predicted else None,
                "recall": float(confusion[index, index] / support) if support else None,
            }
        return result

    object_material_metrics = {}
    for index, name in enumerate(labels["materials"]):
        support = int(object_material_tp[index] + object_material_fn[index])
        predicted = int(object_material_tp[index] + object_material_fp[index])
        object_material_metrics[name] = {
            "positive_support": support,
            "precision": float(object_material_tp[index] / predicted) if predicted else None,
            "recall": float(object_material_tp[index] / support) if support else None,
        }
    boundary_precision = boundary_tp / (boundary_tp + boundary_fp) if boundary_count and boundary_tp + boundary_fp else None
    boundary_recall = boundary_tp / (boundary_tp + boundary_fn) if boundary_count and boundary_tp + boundary_fn else None
    boundary_f1 = 2 * boundary_tp / (2 * boundary_tp + boundary_fp + boundary_fn) if boundary_count and 2 * boundary_tp + boundary_fp + boundary_fn else None
    report = {
        "scope": "same-source development validation",
        "weights_sha256": _sha256(args.weights),
        "weights_bytes": args.weights.stat().st_size,
        "checkpoint": str(args.weights.resolve()), "device": str(device),
        "samples": len(dataset),
        "supervision_source_counts": provenance_counts,
        "review_counts": reviewed_counts,
        "scalar_mae_normalized_0_1": {
            name: scalar_sums[name] / scalar_counts[name] if scalar_counts[name] else None
            for name in scalar_names},
        "scalar_labeled_pixels": scalar_counts,
        "base_depth_mae_labpbr_alpha_steps":
            scalar_sums["base_depth"] / scalar_counts["base_depth"] * 255.0
            if scalar_counts["base_depth"] else None,
        "material_pixel_accuracy": material_correct / material_count if material_count else None,
        "material_labeled_pixels": material_count,
        "structure_labeled_pixels": structure_count,
        "metal_type": {
            "raw_pixel_accuracy": int(metal_confusion_raw.diag().sum()) /
                                  int(metal_confusion_raw.sum()) if metal_confusion_raw.sum() else None,
            "constrained_pixel_accuracy": int(metal_confusion_constrained.diag().sum()) /
                                          int(metal_confusion_constrained.sum()) if metal_confusion_constrained.sum() else None,
            "labeled_pixels": int(metal_confusion_raw.sum()),
            "raw_classes": metal_metrics(metal_confusion_raw),
            "constrained_classes": metal_metrics(metal_confusion_constrained),
            "constraint": "metal reflection requires recognized object type, object composition=metal and local pixel material=metal",
        },
        "wood_only_tool_false_metal_rate": {
            "samples": wooden_tool_samples,
            "labeled_pixels": wooden_tool_pixels,
            "raw_rate": wooden_tool_raw_metal_pixels / wooden_tool_pixels if wooden_tool_pixels else None,
            "constrained_rate": wooden_tool_constrained_metal_pixels /
                               wooden_tool_pixels if wooden_tool_pixels else None,
            "samples_detail": wooden_tool_details,
        },
        "object_type_accuracy": object_correct / object_count if object_count else None,
        "object_type_labeled_samples": object_count,
        "object_material_tag_accuracy_known":
            object_material_correct / object_material_count if object_material_count else None,
        "object_material_known_tags": object_material_count,
        "object_material_tags": object_material_metrics,
        "boundary_threshold": 0.5,
        "boundary": {"precision": boundary_precision, "recall": boundary_recall,
                     "f1": boundary_f1, "labeled_pixels": boundary_count,
                     "axis_labeled_pixels": boundary_axis_counts},
        "note": "same-source development validation; no independent held-out or cross-mod claim.",
    }
    print(json.dumps(report, ensure_ascii=False, indent=2), flush=True)
    return 0


def _diagnose(args: argparse.Namespace) -> int:
    from integratepbr_engine.diagnostics import diagnose
    result = diagnose(args.dataset_root, args.manifest, args.weights, args.labels,
                      args.output, cpu=args.cpu)
    print(json.dumps(result, ensure_ascii=False, indent=2), flush=True)
    return 0


def _generate(args: argparse.Namespace) -> int:
    import sys
    from integratepbr_engine.pipeline import generate_job
    try:
        result = generate_job(args.job, args.job_root, args.weights, args.labels)
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False, allow_nan=False), flush=True)
    if result["status"] == "failed":
        print(result["error"]["message"], file=sys.stderr)
        return 1
    return 0


def _prepare_snapshot(args: argparse.Namespace) -> int:
    import sys
    from integratepbr_engine.snapshot import prepare_snapshot
    try:
        report = prepare_snapshot(args.snapshot_root, args.output_root, args.package_metadata,
                                  args.declarations, experimental=args.experimental_offline_plane)
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(json.dumps(report, ensure_ascii=False, allow_nan=False), flush=True)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(prog="integrate-pbr-engine")
    sub = parser.add_subparsers(dest="command", required=True)
    train = sub.add_parser("train", help="train from aligned paired texture/map samples")
    train.add_argument("--dataset-root", type=Path, required=True)
    train.add_argument("--train-manifest", type=Path, required=True)
    train.add_argument("--validation-manifest", type=Path, required=True)
    train.add_argument("--labels", type=Path,
                       default=Path(__file__).resolve().parents[3] / "contracts" / "labels.json")
    train.add_argument("--output", type=Path, required=True)
    train.add_argument("--init-weights", type=Path,
                       help="optional safetensors checkpoint used to warm-start training")
    train.add_argument("--epochs", type=int, default=100)
    train.add_argument("--batch-size", type=int, default=8)
    train.add_argument("--learning-rate", type=float, default=2e-4)
    train.add_argument("--seed", type=int, default=20260930)
    train.add_argument("--cpu", action="store_true")
    train.set_defaults(handler=_train)
    reference = sub.add_parser("prepare-reference",
                               help="prepare exact paired LabPBR samples from reference ZIPs")
    reference.add_argument("--reference-dir", type=Path, required=True)
    reference.add_argument("--output", type=Path, required=True)
    reference.add_argument("--labels", type=Path,
                           default=Path(__file__).resolve().parents[3] / "contracts" / "labels.json")
    reference.add_argument("--limit", type=int, default=240)
    reference.add_argument("--seed", type=int, default=20260930)
    reference.set_defaults(handler=_prepare_reference)
    review = sub.add_parser("review-packet", help="prepare sparse reference review packet")
    review.add_argument("--dataset-root", type=Path, required=True)
    review.add_argument("--manifest", type=Path, required=True)
    review.add_argument("--training-root", type=Path, required=True)
    review.add_argument("--output", type=Path, required=True)
    review.add_argument("--limit", type=int, default=16)
    review.add_argument("--seed", type=int, default=20260930)
    review.set_defaults(handler=_review_packet)
    imported = sub.add_parser("import-review", help="import approved sparse reviews")
    imported.add_argument("--packet", type=Path, required=True)
    imported.add_argument("--training-root", type=Path, required=True)
    imported.add_argument("--output", type=Path, required=True)
    imported.set_defaults(handler=_import_review)
    evaluate = sub.add_parser("evaluate", help="report held-out pixel and map metrics")
    evaluate.add_argument("--dataset-root", type=Path, required=True)
    evaluate.add_argument("--manifest", type=Path, required=True)
    evaluate.add_argument("--weights", type=Path, required=True)
    evaluate.add_argument("--labels", type=Path,
                          default=Path(__file__).resolve().parents[3] / "contracts" / "labels.json")
    evaluate.add_argument("--batch-size", type=int, default=8)
    evaluate.add_argument("--cpu", action="store_true")
    evaluate.set_defaults(handler=_evaluate)
    diagnostic = sub.add_parser("diagnose", help="offline scratch-checkpoint diagnostics")
    diagnostic.add_argument("--dataset-root", type=Path, required=True)
    diagnostic.add_argument("--manifest", type=Path, required=True)
    diagnostic.add_argument("--weights", type=Path, required=True)
    diagnostic.add_argument("--labels", type=Path,
                            default=Path(__file__).resolve().parents[3] / "contracts" / "labels.json")
    diagnostic.add_argument("--output", type=Path, required=True)
    diagnostic.add_argument("--cpu", action="store_true")
    diagnostic.set_defaults(handler=_diagnose)
    generate = sub.add_parser("generate", help="experimental static CPU offline generation")
    for flag in ("job", "job-root", "weights", "labels"):
        generate.add_argument("--" + flag, type=Path, required=True)
    generate.set_defaults(handler=_generate)
    snapshot = sub.add_parser("prepare-snapshot", help="validate development snapshot and prepare finite offline queue")
    snapshot.add_argument("--snapshot-root", type=Path, required=True)
    snapshot.add_argument("--output-root", type=Path, required=True)
    snapshot.add_argument("--package-metadata", type=Path)
    snapshot.add_argument("--declarations", type=Path)
    snapshot.add_argument("--experimental-offline-plane", action="store_true")
    snapshot.set_defaults(handler=_prepare_snapshot)
    args = parser.parse_args()
    return args.handler(args)


if __name__ == "__main__":
    raise SystemExit(main())

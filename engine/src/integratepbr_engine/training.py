"""Masked multi-task losses and a single repeatable training entry point."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from .model_package import ARCHITECTURE
from .preprocess import CURRENT_PREPROCESS_VERSION

try:
    import torch
    from torch import Tensor
    import torch.nn.functional as F
except ImportError as exc:
    raise RuntimeError("Training requires the optional 'train' dependencies") from exc


DEFAULT_LOSS_WEIGHTS = {
    "object_type": 0.5, "object_materials": 0.5, "material": 1.0,
    "structure": 1.0, "boundary": 1.0, "base_depth": 1.0,
    "fine_depth": 0.5, "smoothness": 0.5, "dielectric_f0": 0.25,
    "metal_type": 0.5, "ao": 0.25,
}


def _to_device(value, device: torch.device):
    if isinstance(value, Tensor):
        return value.to(device, non_blocking=True)
    if isinstance(value, dict):
        return {k: _to_device(v, device) for k, v in value.items()}
    if isinstance(value, list):
        return [_to_device(v, device) for v in value]
    return value


def _masked_smooth_l1(prediction: Tensor, target: Tensor, valid: Tensor) -> Tensor:
    mask = valid.bool() & torch.isfinite(target)
    if not mask.any():
        return prediction.sum() * 0.0
    return F.smooth_l1_loss(prediction.squeeze(1)[mask], target[mask])


def _masked_classification(logits: Tensor, target: Tensor, valid: Tensor, *,
                           balance_classes: bool = False) -> Tensor:
    labels = target.long()
    mask = valid.bool() & (labels >= 0) & (labels != 255)
    if not mask.any():
        return logits.sum() * 0.0
    selected_logits = logits.permute(0, 2, 3, 1)[mask]
    selected_labels = labels[mask]
    if not balance_classes:
        return F.cross_entropy(selected_logits, selected_labels)
    # LabPBR metal codes occupy a tiny fraction of pixels. Inverse-square-root
    # frequency weighting counters the non-metal majority without exploding
    # gradients for rare alloys.
    counts = torch.bincount(selected_labels, minlength=logits.shape[1]).float()
    class_weights = counts.clamp_min(1.0).rsqrt()
    class_weights = class_weights / class_weights[selected_labels].mean().detach()
    sample_weights = class_weights[selected_labels]
    per_pixel = F.cross_entropy(selected_logits, selected_labels, reduction="none")
    return (per_pixel * sample_weights).sum() / sample_weights.sum().clamp_min(1e-8)


def multi_task_loss(prediction, batch: Mapping[str, object],
                    weights: Mapping[str, float] = DEFAULT_LOSS_WEIGHTS
                    ) -> tuple[Tensor, dict[str, float]]:
    targets = batch["targets"]
    valid = batch["valid"][:, 0] > 0.5
    losses: dict[str, Tensor] = {}
    object_type = batch["object_type"]
    object_type_mask = object_type != -100
    if object_type_mask.any():
        losses["object_type"] = F.cross_entropy(
            prediction.object_type[object_type_mask], object_type[object_type_mask])
    else:
        losses["object_type"] = prediction.object_type.sum() * 0.0
    multilabel = batch["object_materials"]
    material_mask = torch.isfinite(multilabel)
    if material_mask.any():
        losses["object_materials"] = F.binary_cross_entropy_with_logits(
            prediction.object_materials[material_mask], multilabel[material_mask])
    else:
        losses["object_materials"] = prediction.object_materials.sum() * 0.0
    losses["material"] = _masked_classification(prediction.material, targets["material"], valid)
    losses["structure"] = _masked_classification(prediction.structure, targets["structure"], valid)
    boundary_logits = prediction.boundary
    boundary_values = torch.stack((targets["boundary_x"], targets["boundary_y"]), dim=1)
    boundary_mask = valid[:, None] & torch.isfinite(boundary_values)
    if boundary_mask.any():
        selected_boundary = boundary_values[boundary_mask]
        positives = selected_boundary.sum()
        negatives = selected_boundary.numel() - positives
        positive_weight = (negatives / positives.clamp_min(1.0)).sqrt().clamp(1.0, 20.0)
        losses["boundary"] = F.binary_cross_entropy_with_logits(
            boundary_logits[boundary_mask], selected_boundary,
            pos_weight=positive_weight)
    else:
        losses["boundary"] = boundary_logits.sum() * 0.0
    for key, output in (("base_depth", prediction.base_depth), ("fine_depth", prediction.fine_depth),
                        ("smoothness", prediction.smoothness),
                        ("dielectric_f0", prediction.dielectric_f0), ("ao", prediction.ao)):
        losses[key] = _masked_smooth_l1(output, targets[key], valid)
    losses["metal_type"] = _masked_classification(prediction.metal_type,
                                                   targets["metal_type"], valid,
                                                   balance_classes=True)
    total = sum(losses[name] * weights[name] for name in losses)
    return total, {name: float(value.detach()) for name, value in losses.items()}


def fit(model, train_loader, validation_loader, *, epochs: int, learning_rate: float,
        device: torch.device, output_dir: Path, seed: int) -> dict[str, float]:
    """Train once, keep only the best validation weights in safe tensor format."""
    try:
        from safetensors.torch import save_file
    except ImportError as exc:
        raise RuntimeError("Saving model weights requires safetensors; install engine[train]") from exc
    import json

    model.to(device)
    optimizer = torch.optim.AdamW(model.parameters(), lr=learning_rate, weight_decay=0.01)
    scheduler = torch.optim.lr_scheduler.ReduceLROnPlateau(
        optimizer, mode="min", patience=max(2, epochs // 20), factor=0.5)
    scaler = torch.amp.GradScaler("cuda", enabled=device.type == "cuda")
    output_dir.mkdir(parents=True, exist_ok=True)
    best = float("inf")
    best_epoch = 0
    stale = 0
    patience = max(8, epochs // 10)

    for epoch in range(1, epochs + 1):
        model.train()
        for batch in train_loader:
            batch = _to_device(batch, device)
            optimizer.zero_grad(set_to_none=True)
            with torch.autocast(device_type=device.type, dtype=torch.float16,
                                enabled=device.type == "cuda"):
                prediction = model(batch["image"], batch["metadata"], batch["name_bytes"])
                loss, _ = multi_task_loss(prediction, batch)
            scaler.scale(loss).backward()
            scaler.unscale_(optimizer)
            torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            scaler.step(optimizer)
            scaler.update()

        model.eval()
        total, batches = 0.0, 0
        with torch.inference_mode():
            for batch in validation_loader:
                batch = _to_device(batch, device)
                with torch.autocast(device_type=device.type, dtype=torch.float16,
                                    enabled=device.type == "cuda"):
                    prediction = model(batch["image"], batch["metadata"], batch["name_bytes"])
                    loss, _ = multi_task_loss(prediction, batch)
                if torch.isfinite(loss):
                    total += float(loss)
                    batches += 1
        if batches != len(validation_loader):
            raise RuntimeError("validation produced a non-finite loss or no batches; no model was saved")
        validation_loss = total / batches
        scheduler.step(validation_loss)
        print(json.dumps({"epoch": epoch, "validation_loss": validation_loss,
                          "learning_rate": optimizer.param_groups[0]["lr"]}), flush=True)
        if validation_loss < best:
            best = validation_loss
            best_epoch = epoch
            stale = 0
            weights = {k: v.detach().cpu().contiguous()
                       for k, v in model.state_dict().items()}
            save_file(weights, str(output_dir / "model.safetensors"))
            (output_dir / "model-metadata.json").write_text(json.dumps({
                "architecture": ARCHITECTURE, "preprocessing_version": CURRENT_PREPROCESS_VERSION, "schema_version": 2,
                "best_epoch": best_epoch, "validation_loss": best,
                "parameter_count": sum(p.numel() for p in model.parameters()),
                "weights_file": "model.safetensors",
            }, indent=2) + "\n", "utf-8")
        else:
            stale += 1
            if stale >= patience:
                break
    return {"best_validation_loss": best, "best_epoch": best_epoch,
            "completed_epochs": epoch, "weight_decay": 0.01,
            "early_stop_patience": patience,
            "scheduler_patience": max(2, epochs // 20)}

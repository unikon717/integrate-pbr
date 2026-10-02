"""Conservative experimental numeric constraints, independent of source color."""
import math
import numpy as np
import torch
from .network import constrained_metal_probabilities


def validate_predictions(prediction, labels, height, width):
    classes = {"object_type": len(labels["objects"]), "object_materials": len(labels["materials"]),
               "material": len(labels["materials"]), "structure": len(labels["structures"]),
               "metal_type": len(labels["metals"]), "boundary": 2}
    for name in prediction._fields:
        value = getattr(prediction, name)
        expected = (1, classes[name]) if name in ("object_type", "object_materials") else (1, classes.get(name, 1), height, width)
        if not isinstance(value, torch.Tensor) or tuple(value.shape) != expected or not torch.isfinite(value).all():
            raise ValueError(f"invalid prediction head: {name}")


def constrain_predictions(prediction, valid, labels, *, max_depth_alpha=2.0):
    if isinstance(max_depth_alpha, bool) or not isinstance(max_depth_alpha, (int, float)) or not math.isfinite(max_depth_alpha) or not 0 <= max_depth_alpha <= 2:
        raise ValueError("invalid depth limit")
    valid = np.asarray(valid, dtype=bool)
    if valid.ndim != 2:
        raise ValueError("validity must be HxW")
    validate_predictions(prediction, labels, *valid.shape)
    def scalar(name):
        return getattr(prediction, name)[0, 0].detach().cpu().numpy().astype(np.float32).copy()
    depth = np.clip(255 * scalar("base_depth"), 0, max_depth_alpha)
    depth_byte = np.floor(depth).astype(np.uint8)
    height = 255 - depth_byte
    metal = constrained_metal_probabilities(prediction, metal_material_index=labels["materials"].index("metal"), unknown_object_type_index=labels["objects"].index("unknown"), threshold=0.5).argmax(1)[0].cpu().numpy()
    # The shared gate's no-metal channel is index zero; require that vocabulary contract.
    if labels["metals"][0] != "none":
        raise ValueError("none metal must be index zero")
    height[~valid] = 255
    depth[~valid] = 0
    depth_byte[~valid] = 0
    metal[~valid] = 0
    return {"depth": depth, "depth_byte": depth_byte, "height": height,
            "smoothness": np.clip(scalar("smoothness"), 0, 1),
            "dielectric_f0": np.clip(scalar("dielectric_f0"), 0, 229 / 255),
            "ao": np.clip(scalar("ao"), 0, 1), "metal_indices": metal,
            "valid": valid.copy(), "fine_depth_applied": False}

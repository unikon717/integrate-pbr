"""Versioned, native-pixel model input preprocessing."""

import numpy as np

CURRENT_PREPROCESS_VERSION = "rgba5-v2"
LEGACY_ALPHA_PREPROCESS_VERSION = "rgba5-legacy-alpha-v1"


def preprocess_rgba(rgba: np.ndarray, *, version: str) -> np.ndarray:
    if not isinstance(rgba, np.ndarray) or rgba.dtype != np.uint8 or rgba.ndim != 3 or rgba.shape[2] != 4:
        raise ValueError("expected uint8 H×W×4 RGBA")
    if version not in (CURRENT_PREPROCESS_VERSION, LEGACY_ALPHA_PREPROCESS_VERSION):
        raise ValueError(f"unsupported preprocessing version: {version}")
    normalized = rgba.astype(np.float32) / np.float32(255)
    alpha = normalized[:, :, 3:4]
    if version == LEGACY_ALPHA_PREPROCESS_VERSION:
        alpha = alpha / np.float32(255)
    valid = (rgba[:, :, 3:4] > 0).astype(np.float32)
    return np.concatenate((normalized[:, :, :3], alpha, valid), axis=2)

"""Fail-closed local checkpoint identity for the current model."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

from .preprocess import CURRENT_PREPROCESS_VERSION

PACKAGE_SCHEMA_VERSION = 1
ARCHITECTURE = "context_swin_unet_v2"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def create_metadata(weights: Path, labels: Path, parameter_count: int, **provenance) -> dict:
    if type(parameter_count) is not int or parameter_count <= 0:
        raise ValueError("invalid parameter count")
    if weights.name != "model.safetensors":
        raise ValueError("weights must use the local model.safetensors filename")
    return {**provenance, "package_schema_version": PACKAGE_SCHEMA_VERSION,
            "architecture": ARCHITECTURE, "preprocessing_version": CURRENT_PREPROCESS_VERSION,
            "labels_sha256": sha256(labels), "weights_file": weights.name,
            "weights_sha256": sha256(weights), "parameter_count": parameter_count}


def validate_package(weights: Path, labels: Path, *, parameter_count: int | None = None) -> dict:
    weights = weights.resolve()
    metadata_path = weights.parent / "model-metadata.json"
    try:
        metadata = json.loads(metadata_path.read_text("utf-8"))
    except (FileNotFoundError, json.JSONDecodeError) as exc:
        raise ValueError("checkpoint identity metadata missing or invalid; legacy incompatible") from exc
    if not isinstance(metadata, dict):
        raise ValueError("invalid checkpoint metadata")
    if "preprocessing_version" not in metadata:
        raise ValueError("checkpoint preprocessing metadata missing; legacy incompatible")
    expected = {"package_schema_version": PACKAGE_SCHEMA_VERSION, "architecture": ARCHITECTURE,
                "preprocessing_version": CURRENT_PREPROCESS_VERSION}
    for key, value in expected.items():
        if type(metadata.get(key)) is not type(value) or metadata[key] != value:
            raise ValueError(f"checkpoint identity mismatch: {key}")
    for key in ("labels_sha256", "weights_sha256"):
        if type(metadata.get(key)) is not str or not re.fullmatch(r"[0-9a-f]{64}", metadata[key]):
            raise ValueError(f"invalid checkpoint digest: {key}")
    filename = metadata.get("weights_file")
    if type(filename) is not str or not filename or any(c in filename for c in "/\\:") or filename in (".", ".."):
        raise ValueError("unsafe checkpoint weight filename")
    candidate = (weights.parent / filename).resolve()
    if candidate.parent != weights.parent or candidate != weights:
        raise ValueError("checkpoint weight filename mismatch")
    count = metadata.get("parameter_count")
    if type(count) is not int or count <= 0 or (parameter_count is not None and count != parameter_count):
        raise ValueError("checkpoint parameter count mismatch")
    for key, path in (("labels_sha256", labels), ("weights_sha256", weights)):
        if metadata[key] != sha256(path):
            raise ValueError(f"checkpoint identity mismatch: {key}")
    return metadata

"""Offline, provenance-aware render-surface usage policy resolver (v1)."""

from __future__ import annotations

import json
from pathlib import Path

DEFAULT_CONTRACT = Path(__file__).resolve().parents[3] / "contracts/surface-usage.v1.json"
SURFACES = {"item_surface", "block_surface"}


def load_usage_contract(path: Path = DEFAULT_CONTRACT) -> dict:
    """Load and validate a version-one surface usage contract."""
    contract = json.loads(Path(path).read_text("utf-8"))
    return _validate_contract(contract)


def _validate_contract(contract: dict) -> dict:
    """Validate both loaded and caller-supplied contracts through one path."""
    if not isinstance(contract, dict) or contract.get("schema_version") != 1:
        raise ValueError("unsupported or invalid surface usage contract schema")
    profiles = contract.get("profiles")
    if not isinstance(profiles, dict) or set(profiles) != SURFACES or any(
            not isinstance(profile, dict) or not isinstance(profile.get("guidance"), str)
            or not profile["guidance"].strip() for profile in profiles.values()):
        raise ValueError("unsupported or invalid surface usage contract schema")
    statuses = contract.get("statuses_without_profile")
    if not isinstance(statuses, list) or len(statuses) != 2 or set(statuses) != {"unresolved", "conflict"}:
        raise ValueError("invalid status contract")
    rules = contract.get("rules")
    if not isinstance(rules, dict) or set(rules) != {"verified_item", "verified_block", "conflict", "unresolved"}:
        raise ValueError("invalid rule IDs")
    if any(not isinstance(value, str) or not value.strip() for value in rules.values()) or len(set(rules.values())) != 4:
        raise ValueError("invalid or duplicate rule ID")
    annotations = contract.get("annotations")
    if not isinstance(annotations, list):
        raise ValueError("invalid annotations")
    identities = set()
    for row in annotations:
        if not isinstance(row, dict):
            raise ValueError("invalid annotation")
        identity = (row.get("sample_id"), row.get("reference_entry"))
        if not all(isinstance(part, str) and part for part in identity) or identity in identities:
            raise ValueError("invalid or duplicate annotation identity")
        identities.add(identity)
        if (row.get("source") != "user_confirmed" or row.get("reviewed_training_label") is not False
                or row.get("render_surface") not in SURFACES or row.get("region_geometry") != "unknown"
                or not isinstance(row.get("role"), str) or not row["role"].strip()
                or not isinstance(row.get("guidance"), str) or not row["guidance"].strip()):
            raise ValueError("invalid annotation")
    return contract


def _normalize_evidence(evidence) -> list[dict]:
    normalized = {}
    for record in evidence:
        if not isinstance(record, dict) or set(record) - {"kind", "value", "source", "verified", "owner", "model", "state", "renderer", "resource"}:
            raise ValueError("malformed usage evidence record")
        kind, value, source, verified = (record.get(key) for key in ("kind", "value", "source", "verified"))
        if kind not in {"render_surface", "owner_use"} or not isinstance(value, str) or not value or not isinstance(source, str) or not source or type(verified) is not bool:
            raise ValueError("malformed usage evidence record")
        if kind == "render_surface" and verified and value not in SURFACES:
            raise ValueError(f"unknown verified render surface: {value}")
        if verified:
            for key in ("owner", "model", "state", "renderer", "resource"):
                if not isinstance(record.get(key), str) or not record[key].strip():
                    raise ValueError(f"verified usage evidence requires {key} provenance")
        clean = {key: record[key] for key in sorted(record)}
        normalized[json.dumps(clean, sort_keys=True)] = clean
    return [normalized[key] for key in sorted(normalized)]


def resolve_surface_usage(*, resource_id: str | None = None, sample_id: str | None = None,
                          reference_entry: str | None = None, evidence=(), contract: dict | None = None) -> dict:
    """Resolve surface from verified render evidence or an exact confirmed annotation.

    Paths and owner uses only contribute hints; incomplete identities never inherit guidance.
    """
    contract = load_usage_contract() if contract is None else _validate_contract(contract)
    normalized = _normalize_evidence(evidence or ())
    annotation = next((row for row in contract["annotations"] if sample_id == row["sample_id"]
                       and reference_entry == row["reference_entry"]), None) if sample_id and reference_entry else None
    surfaces = {row["value"] for row in normalized if row["kind"] == "render_surface" and row["verified"]
                and row["renderer"].strip().casefold() != "unknown"}
    if annotation:
        surfaces.add(annotation["render_surface"])
    if len(surfaces) > 1:
        status, rule = "conflict", "conflict"
    elif surfaces:
        status = next(iter(surfaces))
        rule = "verified_item" if status == "item_surface" else "verified_block"
    else:
        status, rule = "unresolved", "unresolved"
    hints = set()
    for value in (resource_id, reference_entry):
        if isinstance(value, str):
            parts = value.replace("\\", "/").lower().split("/")
            hints.update(f"path_segment:{part}" for part in parts if part in {"item", "block"})
    hints.update(f"owner_use:{row['value']}" for row in normalized if row["kind"] == "owner_use")
    return {"status": status, "selected_profile": status if status in SURFACES else None,
            "rule_id": contract["rules"][rule], "evidence": normalized, "hints": sorted(hints),
            "guidance": annotation["guidance"] if annotation else None,
            "annotation": annotation}

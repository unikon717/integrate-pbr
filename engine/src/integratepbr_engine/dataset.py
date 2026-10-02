"""Training dataset loader for reviewed, aligned texture/target-map pairs."""

from __future__ import annotations

import json
import hashlib
import io
import math
import random
import re
import zipfile
from collections import defaultdict
from pathlib import Path
from posixpath import dirname
from typing import Any

import numpy as np
from PIL import Image
from .preprocess import CURRENT_PREPROCESS_VERSION, preprocess_rgba

try:
    import torch
    from torch.utils.data import Dataset
except ImportError as exc:
    raise RuntimeError("Dataset loading for training requires the optional 'train' dependencies") from exc


class ReviewedTextureDataset(Dataset[dict[str, Any]]):
    """JSONL manifest + original PNG + NPZ maps, all split by mod/artwork group."""

    REQUIRED_TARGETS = ("material", "structure", "boundary_x", "boundary_y",
                        "base_depth", "fine_depth", "smoothness", "dielectric_f0",
                        "metal_type", "ao")

    def __init__(self, root: Path, manifest: Path, *, material_classes: int,
                 structure_classes: int, object_classes: int, metal_classes: int,
                 preprocessing_version: str = CURRENT_PREPROCESS_VERSION) -> None:
        self.root = root.resolve()
        self.material_classes = material_classes
        self.structure_classes = structure_classes
        self.object_classes = object_classes
        self.metal_classes = metal_classes
        self.preprocessing_version = preprocessing_version
        self.rows = [json.loads(line) for line in manifest.read_text("utf-8").splitlines()
                     if line.strip()]
        self._validate_groups()

    def _resolve(self, relative: str) -> Path:
        path = (self.root / relative).resolve()
        if self.root not in path.parents:
            raise ValueError(f"dataset path escapes the selected root: {relative}")
        return path

    def _validate_groups(self) -> None:
        seen: set[str] = set()
        for row in self.rows:
            for key in ("sample_id", "source_artwork_id", "mod_id", "material_family",
                        "source", "targets", "metadata", "object_type"):
                if key not in row:
                    raise ValueError(f"sample {row.get('sample_id', '?')} lacks {key}")
            if row["sample_id"] in seen:
                raise ValueError(f"duplicate sample_id: {row['sample_id']}")
            seen.add(row["sample_id"])
            if len(row["metadata"]) != 64:
                raise ValueError(f"{row['sample_id']}: metadata must have 64 values")
            if not all(np.isfinite(row["metadata"])):
                raise ValueError(f"{row['sample_id']}: metadata contains a non-finite value")
            if row["object_type"] is not None and not 0 <= row["object_type"] < self.object_classes:
                raise ValueError(f"{row['sample_id']}: object_type is outside the label table")
            materials = row.get("object_materials", [])
            if materials and len(materials) != self.material_classes:
                raise ValueError(f"{row['sample_id']}: object_materials must match material labels")
            if any(value not in (0, 1, None) for value in materials):
                raise ValueError(f"{row['sample_id']}: object_materials values must be 0, 1 or null")
            exact_reference = row.get("supervision_source") == "exact_reference_pbr_pair"
            if not row.get("reviewed", False) and not exact_reference:
                raise ValueError(f"{row['sample_id']}: unreviewed samples cannot train the model")

    def __len__(self) -> int:
        return len(self.rows)

    def __getitem__(self, index: int) -> dict[str, Any]:
        row = self.rows[index]
        with Image.open(self._resolve(row["source"])) as opened:
            rgba = np.asarray(opened.convert("RGBA"), dtype=np.uint8).copy()
        inputs = preprocess_rgba(rgba, version=self.preprocessing_version)
        valid = inputs[:, :, 4:5]
        with np.load(self._resolve(row["targets"]), allow_pickle=False) as maps:
            targets = {key: np.array(maps[key], copy=True) for key in maps.files}
        height, width = inputs.shape[:2]
        for key in self.REQUIRED_TARGETS:
            if key not in targets:
                raise ValueError(f"{row['sample_id']}: target map {key} is missing")
            if targets[key].shape != (height, width):
                raise ValueError(f"{row['sample_id']}: target {key} does not align with source")
        reference_only = (not row.get("reviewed", False) and
                          row.get("supervision_source") == "exact_reference_pbr_pair")
        if reference_only:
            # Old seed archives included guesses. Never train semantic or invented
            # geometry targets from an unreviewed reference pair.
            observed_metal = (valid[:, :, 0] > 0) & (targets["metal_type"] > 0) & (targets["metal_type"] < self.metal_classes)
            targets["metal_type"][valid[:, :, 0] == 0] = 255
            targets["material"][:] = 255
            metal_index = 3  # contracts/labels.json material index
            targets["material"][observed_metal] = metal_index
            targets["structure"][:] = 255
            for key in ("boundary_x", "boundary_y", "fine_depth"):
                targets[key][:] = np.nan
        for key in ("base_depth", "fine_depth", "smoothness", "dielectric_f0", "ao",
                    "boundary_x", "boundary_y"):
            finite = targets[key][np.isfinite(targets[key])]
            if finite.size and (finite.min() < 0.0 or finite.max() > 1.0):
                raise ValueError(f"{row['sample_id']}: target {key} must be normalized to [0,1]")
        for key, count in (("material", self.material_classes),
                           ("structure", self.structure_classes),
                           ("metal_type", self.metal_classes)):
            labeled = targets[key][targets[key] != 255]
            if labeled.size and (labeled.min() < 0 or labeled.max() >= count):
                raise ValueError(f"{row['sample_id']}: target {key} is outside the label table")
        return {
            "image": torch.from_numpy(inputs).permute(2, 0, 1),
            "targets": {k: torch.from_numpy(v.astype(np.float32, copy=False))
                        for k, v in targets.items()},
            "metadata": torch.tensor(row["metadata"], dtype=torch.float32),
            "name_bytes": torch.tensor(list(row.get("name", "").encode("utf-8")[:96]),
                                       dtype=torch.long),
            "object_type": torch.tensor(-100 if reference_only or row["object_type"] is None
                                         else row["object_type"], dtype=torch.long),
            "object_materials": torch.tensor(
                [float("nan") if value is None else float(value)
                 for value in ([1 if i == metal_index and observed_metal.any() else None
                                for i in range(self.material_classes)] if reference_only else
                               (row.get("object_materials") or
                                [None] * self.material_classes))], dtype=torch.float32),
            "sample_id": row["sample_id"],
            "supervision_source": row.get("supervision_source", "reviewed_annotation"),
            "reviewed": bool(row.get("reviewed", False)),
        }


def collate_native(samples: list[dict[str, Any]]) -> dict[str, Any]:
    """Pad variable texture sizes to a multiple of eight and mask padding labels."""
    batch = len(samples)
    max_h = max(s["image"].shape[1] for s in samples)
    max_w = max(s["image"].shape[2] for s in samples)
    out_h, out_w = (max_h + 7) // 8 * 8, (max_w + 7) // 8 * 8
    images = torch.zeros(batch, 5, out_h, out_w)
    valid = torch.zeros(batch, 1, out_h, out_w)
    target_keys = samples[0]["targets"].keys()
    targets: dict[str, torch.Tensor] = {}
    for key in target_keys:
        fill = 255.0 if key in ("material", "structure", "metal_type") else float("nan")
        targets[key] = torch.full((batch, out_h, out_w), fill, dtype=torch.float32)
    for i, sample in enumerate(samples):
        _, h, w = sample["image"].shape
        images[i, :, :h, :w] = sample["image"]
        valid[i, 0, :h, :w] = sample["image"][4]
        for key, value in sample["targets"].items():
            targets[key][i, :h, :w] = value
    images[:, 4:5] = valid
    max_name = max(1, max(s["name_bytes"].numel() for s in samples))
    names = torch.zeros(batch, max_name, dtype=torch.long)
    for i, sample in enumerate(samples):
        names[i, :sample["name_bytes"].numel()] = sample["name_bytes"]
    return {
        "image": images, "valid": valid, "targets": targets,
        "metadata": torch.stack([s["metadata"] for s in samples]),
        "name_bytes": names,
        "object_type": torch.stack([s["object_type"] for s in samples]),
        "object_materials": torch.stack([s["object_materials"] for s in samples]),
        "sample_id": [s["sample_id"] for s in samples],
        "supervision_source": [s["supervision_source"] for s in samples],
        "reviewed": [s["reviewed"] for s in samples],
    }


# Reference-pack seed preparation: exact color/_n/_s pairs only. Semantic labels
# inferred from vanilla paths stay explicitly weak; structural classes stay unknown.
_WOOD_WORDS = ("oak", "birch", "spruce", "jungle", "acacia", "mangrove", "cherry",
               "bamboo", "crimson", "warped", "pale_oak", "plank", "log", "wood")
_STONE_WORDS = ("stone", "brick", "cobble", "deepslate", "tuff", "granite", "diorite",
                "andesite", "basalt", "blackstone", "quartz", "slate", "terracotta",
                "sandstone")
_METAL_WORDS = ("iron", "gold", "copper", "steel", "silver", "bronze", "platinum",
                "aluminum", "metal", "netherite", "lead", "tin", "zinc", "nickel")
_PLANT_WORDS = ("leaves", "sapling", "flower", "fern", "vine", "grass", "roots",
                "moss", "cactus", "azalea", "lily", "petals")
_SPECIES = ("dark_oak", "pale_oak", "mangrove", "crimson", "warped", "cherry", "bamboo",
            "spruce", "jungle", "acacia", "birch", "oak")


def _has_name_token(stem: str, words: tuple[str, ...]) -> bool:
    padded = f"_{stem.lower()}_"
    return any(f"_{word}_" in padded for word in words)


def _reference_category(path: str) -> str:
    stem = Path(path).stem.lower()
    if _has_name_token(stem, ("sand", "dirt", "mud", "gravel", "soil", "grass_block")):
        return "soil_sand"
    if _has_name_token(stem, _PLANT_WORDS):
        return "other"
    if _has_name_token(stem, _WOOD_WORDS + ("wooden",)):
        return "wood"
    if _has_name_token(stem, _STONE_WORDS + ("cobblestone",)):
        return "masonry"
    if _has_name_token(stem, _METAL_WORDS +
                       ("sword", "pickaxe", "axe", "hoe", "shovel", "armor", "chainmail")):
        return "metal"
    return "other"


def _reference_base_material(path: str, material_ids: dict[str, int]) -> int | None:
    stem = Path(path).stem.lower()
    if _has_name_token(stem, ("ore",)):
        return material_ids.get("stone")
    if _has_name_token(stem, ("glass", "pane")):
        return material_ids.get("glass")
    if _has_name_token(stem, ("sand", "soul_sand")):
        return material_ids.get("sand")
    if _has_name_token(stem, ("dirt", "mud", "grass_block", "podzol", "mycelium")):
        return material_ids.get("soil")
    if _has_name_token(stem, _PLANT_WORDS):
        return material_ids.get("plant")
    if _has_name_token(stem, ("leather",)):
        return material_ids.get("leather")
    if _has_name_token(stem, ("wool", "cloth", "fabric", "banner")):
        return material_ids.get("fabric")
    if _has_name_token(stem, ("terracotta", "brick", "bricks", "pottery")) \
            and not _has_name_token(stem, ("stone", "cobblestone")):
        return material_ids.get("ceramic")
    if _has_name_token(stem, _STONE_WORDS + ("cobblestone",)):
        return material_ids.get("stone")
    if _has_name_token(stem, _METAL_WORDS) and _has_name_token(
            stem, ("block", "ingot", "nugget", "raw", "door", "trapdoor")):
        return material_ids.get("metal")
    if _has_name_token(stem, _WOOD_WORDS + ("wooden", "door", "trapdoor", "fence",
                                             "sign", "boat", "shelf")):
        return material_ids.get("wood")
    if _has_name_token(stem, ("diamond", "emerald", "amethyst", "ruby", "sapphire")):
        return material_ids.get("gem")
    if _has_name_token(stem, _METAL_WORDS) and _has_name_token(
            stem, ("block", "ingot", "nugget", "raw")):
        return material_ids.get("metal")
    return None


def _reference_object_type(path: str, object_ids: dict[str, int]) -> int | None:
    stem = Path(path).stem.lower()
    is_block = "/textures/block/" in path
    if is_block:
        for tokens, label in ((("trapdoor",), "trapdoor"), (("door",), "door"),
                              (("log",), "log"), (("plank", "planks"), "planks"),
                              (("brick", "bricks"), "brick"), (("ore",), "ore"),
                              (_PLANT_WORDS, "plant")):
            if _has_name_token(stem, tokens):
                return object_ids.get(label)
        return object_ids.get("block")
    if _has_name_token(stem, ("sword",)):
        return object_ids.get("weapon")
    if _has_name_token(stem, ("pickaxe", "axe", "hoe", "shovel")):
        return object_ids.get("tool")
    if _has_name_token(stem, ("helmet", "chestplate", "leggings", "boots", "armor")):
        return object_ids.get("armor")
    if _has_name_token(stem, ("ingot",)):
        return object_ids.get("ingot")
    if _has_name_token(stem, ("nugget",)):
        return object_ids.get("item")
    return object_ids.get("item")


def _reference_metadata(path: str, rgba: np.ndarray, object_type: int | None,
                        object_ids: dict[str, int], *, has_pbr: bool) -> list[float]:
    height, width = rgba.shape[:2]
    stem = Path(path).stem.lower()
    obj = next((name for name, index in object_ids.items() if index == object_type), "unknown")
    vector = np.zeros(64, dtype=np.float32)
    vector[0] = float("/textures/block/" in path)
    vector[1] = float("/textures/item/" in path)
    vector[2] = float(obj == "tool")
    vector[3] = float(obj == "weapon")
    vector[4] = float(obj == "armor")
    vector[5] = float(obj == "door")
    vector[6] = float(obj == "trapdoor")
    vector[7] = float(obj == "log")
    vector[8] = float(obj == "planks")
    vector[9] = float(obj == "brick")
    vector[10] = float(obj == "ore")
    vector[11] = float(obj == "ingot")
    vector[13] = float(obj == "plant")
    vector[16] = float(obj in ("tool", "weapon"))
    vector[17] = float(obj in ("tool", "weapon", "armor"))
    vector[18] = float(obj == "armor")
    vector[19] = float(obj in ("tool", "ore", "block"))
    # Leave usage, attack, durability, stackability, renderer and model-context
    # fields at zero: vanilla texture paths do not provide reliable evidence.
    vector[22] = float(np.any(rgba[:, :, 3] < 255))
    vector[23] = float(has_pbr)
    vector[24] = float(_has_name_token(stem, ("ingot",)))
    vector[25] = float(_has_name_token(stem, ("ore",)))
    vector[26] = float(_has_name_token(stem, ("nugget",)))
    vector[27] = float(_has_name_token(stem, ("sapling",)))
    vector[28] = float(_has_name_token(stem, ("log",)))
    vector[29] = float(_has_name_token(stem, ("plank", "planks")))
    vector[32] = min(1.0, math.log2(max(width, height) / max(1, min(width, height))) / 5.0)
    vector[33] = min(1.0, math.log2(max(1, width)) / 8.0)
    vector[34] = min(1.0, math.log2(max(1, height)) / 8.0)
    vector[35] = float(np.mean(rgba[:, :, 3] > 0))
    rgb = rgba[:, :, :3].astype(np.float32) / 255.0
    gray = rgb @ np.array((0.2126, 0.7152, 0.0722), dtype=np.float32)
    vector[36] = min(1.0, float(rgb.std()) * 2.0)
    p05, p95 = np.percentile(gray, (5, 95))
    vector[37] = float(p95 - p05)
    dx = np.abs(np.diff(gray, axis=1)) if width > 1 else np.zeros((height, 0))
    dy = np.abs(np.diff(gray, axis=0)) if height > 1 else np.zeros((0, width))
    count_x = int(np.count_nonzero(dx > 0.08))
    count_y = int(np.count_nonzero(dy > 0.08))
    edges = count_x + count_y
    vector[38] = min(1.0, edges / max(1, dx.size + dy.size))
    vector[39] = count_x / max(1, edges)
    vector[40] = count_y / max(1, edges)
    vector[41] = float(np.mean(np.abs(rgb - rgb[:, ::-1, :])) < 0.1)
    vector[42] = float(np.mean(np.abs(rgb - rgb[::-1, :, :])) < 0.1)
    border = np.concatenate((rgba[0, :, 3], rgba[-1, :, 3], rgba[:, 0, 3], rgba[:, -1, 3]))
    vector[44] = float(np.mean(border == 0))
    vector[63] = 1.0
    return vector.tolist()


def _complete_reference_pairs(archive: zipfile.ZipFile) -> list[str]:
    files = set(archive.namelist())
    normal_bases = {path[:-6] + ".png" for path in files if path.lower().endswith("_n.png")}
    specular_bases = {path[:-6] + ".png" for path in files if path.lower().endswith("_s.png")}
    return sorted(path for path in (normal_bases & specular_bases & files)
                  if path.lower().endswith(".png")
                  and ("/textures/block/" in path or "/textures/item/" in path)
                  and path.startswith("assets/minecraft/"))


def _derivative_group(path: str, category: str) -> str:
    stem = Path(path).stem.lower()
    if category == "wood":
        species = next((word for word in _SPECIES if word in stem), "generic")
        if species != "generic":
            return f"wood:{species}"
        # Keep semantically comparable variants together while allowing a
        # wooden tool to be held out separately from doors/planks for testing.
        for tokens, family in ((('pickaxe',), 'pickaxe'), (('axe',), 'axe'),
                               (('shovel',), 'shovel'), (('hoe',), 'hoe'),
                               (('sword',), 'sword'), (('trapdoor',), 'trapdoor'),
                               (('door',), 'door'), (('log',), 'log'),
                               (('plank', 'planks'), 'planks'),
                               (('fence', 'fence_gate'), 'fence'),
                               (('sign',), 'sign'), (('boat',), 'boat')):
            if _has_name_token(stem, tokens):
                group_family = "tool" if family in {
                    "pickaxe", "axe", "shovel", "hoe", "sword"} else family
                return f"wood:generic:{group_family}:{family}"
        return f"wood:generic:{stem}"
    stem = re.sub(r"^(cracked|mossy|chiseled|polished|cut|smooth|weathered|exposed|oxidized)_", "", stem)
    stem = re.sub(r"_(top|side|front|bottom|lit|on|off|stage\d+)$", "", stem)
    return f"{category}:{stem}"


def _find_components(rows: list[dict[str, Any]]) -> dict[str, str]:
    parent: dict[str, str] = {}

    def find(value: str) -> str:
        parent.setdefault(value, value)
        if parent[value] != value:
            parent[value] = find(parent[value])
        return parent[value]

    def union(left: str, right: str) -> None:
        a, b = find(left), find(right)
        if a != b:
            parent[max(a, b)] = min(a, b)

    for row in rows:
        union("art:" + row["source_artwork_id"], "der:" + row["derivative_group"])
    return {row["sample_id"]: find("art:" + row["source_artwork_id"]) for row in rows}


def prepare_reference_seed(reference_dir: Path, output_root: Path,
                           labels: dict[str, Any], *, limit: int = 240,
                           seed: int = 20260930) -> dict[str, Any]:
    """Extract a small, deterministic seed set from the archive with most exact PBR pairs."""
    material_ids = {name: i for i, name in enumerate(labels["materials"])}
    object_ids = {name: i for i, name in enumerate(labels["objects"])}
    archive_options = []
    for path in sorted(reference_dir.glob("*.zip")):
        with zipfile.ZipFile(path) as archive:
            pairs = _complete_reference_pairs(archive)
        archive_options.append((len(pairs), path, pairs))
    if not archive_options:
        raise FileNotFoundError(f"no reference ZIP packs in {reference_dir}")
    pair_count, archive_path, pairs = max(archive_options, key=lambda value: value[0])
    if pair_count == 0:
        raise ValueError("no exact color + _n + _s triplets were found")
    if output_root.exists() and any(output_root.iterdir()):
        raise FileExistsError(f"refusing to overwrite a non-empty dataset directory: {output_root}")
    output_root.mkdir(parents=True, exist_ok=True)

    buckets: dict[str, list[str]] = defaultdict(list)
    for path in pairs:
        buckets[_reference_category(path)].append(path)
    rng = random.Random(seed)
    for values in buckets.values():
        rng.shuffle(values)
    weights = {"wood": 0.32, "masonry": 0.32, "metal": 0.20,
               "soil_sand": 0.10, "other": 0.06}
    selected: list[tuple[str, str]] = []
    for category, weight in weights.items():
        quota = round(limit * weight)
        selected.extend((category, path) for path in buckets[category][:quota])
    picked = {path for _, path in selected}
    remaining = [(category, path) for category in weights
                 for path in buckets[category] if path not in picked]
    rng.shuffle(remaining)
    selected.extend(remaining[:max(0, limit - len(selected))])
    selected = selected[:limit]

    pack_digest = hashlib.sha256(archive_path.read_bytes()).hexdigest()
    rows: list[dict[str, Any]] = []
    invalid = 0
    with zipfile.ZipFile(archive_path) as archive:
        for category, color_path in selected:
            normal_path = color_path[:-4] + "_n.png"
            specular_path = color_path[:-4] + "_s.png"
            try:
                rgba = np.asarray(Image.open(io.BytesIO(archive.read(color_path))).convert("RGBA"),
                                  dtype=np.uint8).copy()
                normal = np.asarray(Image.open(io.BytesIO(archive.read(normal_path))).convert("RGBA"),
                                    dtype=np.uint8).copy()
                specular = np.asarray(Image.open(io.BytesIO(archive.read(specular_path))).convert("RGBA"),
                                      dtype=np.uint8).copy()
            except Exception:
                invalid += 1
                continue
            if rgba.shape != normal.shape or rgba.shape != specular.shape:
                invalid += 1
                continue
            height, width = rgba.shape[:2]
            if min(height, width) < 8 or max(height, width) > 512:
                invalid += 1
                continue
            valid = rgba[:, :, 3] > 0
            if not valid.any():
                invalid += 1
                continue

            candidate_material = _reference_base_material(color_path, material_ids)
            candidate_object_type = _reference_object_type(color_path, object_ids)
            green = specular[:, :, 1]
            metal = green >= 230
            metal_type = np.zeros((height, width), dtype=np.float32)
            for channel_code in range(230, 238):
                label_name = ("iron", "gold", "aluminum", "chrome", "copper", "lead",
                              "platinum", "silver")[channel_code - 230]
                metal_type[green == channel_code] = (
                    labels["metals"].index(label_name) if label_name in labels["metals"]
                    else labels["metals"].index("generic"))
            metal_type[green >= 238] = labels["metals"].index("generic")
            metal_type[~valid] = 255

            material = np.full((height, width), 255, dtype=np.float32)
            if "metal" in material_ids:
                material[valid & metal] = material_ids["metal"]

            depth = 1.0 - normal[:, :, 3].astype(np.float32) / 255.0
            depth[~valid] = np.nan
            smoothness = specular[:, :, 0].astype(np.float32) / 255.0
            smoothness[~valid] = np.nan
            f0 = specular[:, :, 1].astype(np.float32) / 255.0
            f0[~valid | metal] = np.nan
            ao = normal[:, :, 2].astype(np.float32) / 255.0
            ao[~valid] = np.nan
            fine_depth = np.full((height, width), np.nan, dtype=np.float32)
            structure = np.full((height, width), 255, dtype=np.float32)
            boundary_x = np.full((height, width), np.nan, dtype=np.float32)
            boundary_y = np.full((height, width), np.nan, dtype=np.float32)
            object_materials: list[int | None] = [None] * len(labels["materials"])
            if (valid & metal).any() and "metal" in material_ids:
                object_materials[material_ids["metal"]] = 1

            content_digest = hashlib.sha256(rgba.tobytes()).hexdigest()
            path_digest = hashlib.sha256(color_path.encode("utf-8")).hexdigest()[:10]
            sample_id = f"ref-{content_digest[:16]}-{path_digest}"
            source_relative = f"sources/{sample_id}.png"
            target_relative = f"targets/{sample_id}.npz"
            source_file = output_root / source_relative
            target_file = output_root / target_relative
            source_file.parent.mkdir(parents=True, exist_ok=True)
            target_file.parent.mkdir(parents=True, exist_ok=True)
            Image.fromarray(rgba, "RGBA").save(source_file, format="PNG", optimize=True)
            np.savez_compressed(target_file, material=material, structure=structure,
                                boundary_x=boundary_x, boundary_y=boundary_y,
                                base_depth=depth, fine_depth=fine_depth,
                                smoothness=smoothness, dielectric_f0=f0,
                                metal_type=metal_type, ao=ao)
            derivative_group = _derivative_group(color_path, category)
            rows.append({
                "sample_id": sample_id, "source_artwork_id": content_digest,
                "derivative_group": derivative_group, "mod_id": color_path.split("/")[1],
                "material_family": category, "style_family": "reference_pack_pixel_art",
                "source": source_relative, "targets": target_relative,
                "name": Path(color_path).stem.replace("_", " ").title(),
                "object_type": None,
                "candidate_object_type": candidate_object_type,
                "candidate_base_material": candidate_material,
                "object_materials": object_materials,
                "metadata": _reference_metadata(color_path, rgba, None,
                                                 object_ids, has_pbr=True),
                "reviewed": False, "supervision_source": "exact_reference_pbr_pair",
                "target_provenance": {
                    "base_depth": "direct:_n:A", "smoothness": "direct:_s:R",
                    "dielectric_f0": "direct:_s:G:dielectric", "ao": "direct:_n:B",
                    "metal_type": "direct:_s:G:metal_code_or_dielectric_zero",
                    "material": "observed_positive_metal_only",
                    "object_materials": "observed_positive_metal_only",
                    "object_type": "unavailable", "structure": "unavailable",
                    "boundary_x": "unavailable", "boundary_y": "unavailable",
                    "fine_depth": "unavailable",
                    "candidate_base_material": "filename_candidate",
                    "candidate_object_type": "filename_candidate"},
                "reference_pack": archive_path.name, "reference_pack_sha256": pack_digest,
                "reference_entry": color_path, "annotation_version": 1,
            })

    if len(rows) < 4:
        raise ValueError(f"only {len(rows)} valid reference pairs remained after alignment checks")
    components = _find_components(rows)
    component_keys = sorted(set(components.values()))
    component_split = {key: ("validation" if int(hashlib.sha256(
        f"{seed}:{key}".encode()).hexdigest()[:8], 16) % 5 == 0 else "train")
                       for key in component_keys}
    grouped_rows: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped_rows[components[row["sample_id"]]].append(row)
    strata: dict[str, set[str]] = defaultdict(set)
    for component, group in grouped_rows.items():
        for row in group:
            strata[f"family:{row['material_family']}"].add(component)
            known_materials = sorted(name for name, index in material_ids.items()
                                     if index < len(row.get("object_materials") or []) and
                                     row["object_materials"][index] == 1)
            material_key = ",".join(known_materials) if known_materials else "unknown"
            object_name = (labels["objects"][row["object_type"]]
                           if row["object_type"] is not None else "unknown")
            strata[f"semantic:{object_name}:{material_key}"].add(component)
    for stratum, group_keys in sorted(strata.items()):
        stratum_groups = sorted(group_keys)
        if len(stratum_groups) < 2:
            continue  # A single connected family cannot be split without leakage.
        ranked = sorted(stratum_groups, key=lambda key: hashlib.sha256(
            f"{seed}:{stratum}:{key}".encode()).hexdigest())
        if not any(component_split[key] == "validation" for key in stratum_groups):
            component_split[ranked[0]] = "validation"
        if all(component_split[key] == "validation" for key in stratum_groups):
            component_split[ranked[-1]] = "train"
    if len(component_keys) > 1 and all(value == "train" for value in component_split.values()):
        component_split[min(component_keys)] = "validation"
    if len(component_keys) > 1 and all(value == "validation" for value in component_split.values()):
        component_split[max(component_keys)] = "train"
    manifests = {"train": [], "validation": []}
    sample_splits: dict[str, str] = {}
    for row in rows:
        split = component_split[components[row["sample_id"]]]
        sample_splits[row["sample_id"]] = split
        manifests[split].append(row)
    if not manifests["train"] or not manifests["validation"]:
        raise ValueError("could not create disjoint train/validation groups from the selected pairs")
    for split, split_rows in manifests.items():
        (output_root / f"{split}.jsonl").write_text(
            "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in split_rows), "utf-8")
    families = sorted({row["material_family"] for row in rows})
    category_splits = {family: {
        split: sum(row["material_family"] == family for row in split_rows)
        for split, split_rows in manifests.items()} for family in families}
    semantic_splits: dict[str, dict[str, int]] = {}
    for row in rows:
        known_materials = sorted(name for name, index in material_ids.items()
                                 if index < len(row.get("object_materials") or []) and
                                 row["object_materials"][index] == 1)
        material_key = ",".join(known_materials) if known_materials else "unknown"
        object_name = (labels["objects"][row["object_type"]]
                       if row["object_type"] is not None else "unknown")
        key = f"type={object_name};materials={material_key}"
        split = sample_splits[row["sample_id"]]
        semantic_splits.setdefault(key, {"train": 0, "validation": 0})[split] += 1
    report = {"archive": archive_path.name, "archive_sha256": pack_digest,
              "available_exact_pairs": pair_count, "selected_limit": limit,
              "valid_samples": len(rows), "invalid_or_unaligned": invalid,
              "train_samples": len(manifests["train"]),
              "validation_samples": len(manifests["validation"]),
              "category_counts": {name: sum(row["material_family"] == name for row in rows)
                                  for name in sorted(set(row["material_family"] for row in rows))},
              "category_split_counts": category_splits,
              "semantic_split_counts": semantic_splits,
              "target_provenance": rows[0]["target_provenance"],
              "labels_missing_by_design": ["fine structure classes", "material regions without reliable path evidence"]}
    (output_root / "dataset-report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", "utf-8")
    return report

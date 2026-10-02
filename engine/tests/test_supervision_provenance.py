"""Sparse reference supervision regression checks."""

import json
import tempfile
import unittest
import zipfile
import io
from pathlib import Path

import numpy as np
from PIL import Image

from integratepbr_engine.dataset import ReviewedTextureDataset, collate_native, prepare_reference_seed


class ProvenanceTests(unittest.TestCase):
    def test_prepared_reference_has_only_observed_targets(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            references = root / "references"
            references.mkdir()
            rgba = np.full((8, 8, 4), 255, dtype=np.uint8)
            rgba[0, 2, 3] = 0
            normal = np.full((8, 8, 4), 255, dtype=np.uint8)
            normal[:, :, 3] = np.arange(8, dtype=np.uint8)[:, None] * 16
            normal[:, :, 2] = 128
            specular = np.full((8, 8, 4), 0, dtype=np.uint8)
            specular[:, :, 0] = 192
            specular[:, :, 1] = 64
            specular[0, 0, 1] = 230
            specular[0, 1, 1] = 255
            def png(value):
                buffer = io.BytesIO()
                Image.fromarray(value, "RGBA").save(buffer, format="PNG")
                return buffer.getvalue()
            with zipfile.ZipFile(references / "pack.zip", "w") as archive:
                for i in range(4):
                    prefix = f"assets/minecraft/textures/block/iron_block_{i}"
                    distinct_rgba = rgba.copy()
                    distinct_rgba[7, 7, 0] = i
                    archive.writestr(prefix + ".png", png(distinct_rgba))
                    archive.writestr(prefix + "_n.png", png(normal))
                    archive.writestr(prefix + "_s.png", png(specular))
            labels = json.loads((Path(__file__).resolve().parents[2] /
                                 "contracts/labels.json").read_text())
            report = prepare_reference_seed(references, root / "out", labels, limit=4)
            self.assertEqual(report["valid_samples"], 4)
            rows = [json.loads(line) for split in ("train", "validation")
                    for line in (root / "out" / f"{split}.jsonl").read_text().splitlines()]
            self.assertEqual(len(rows), 4)
            row = rows[0]
            self.assertIsNone(row["object_type"])
            self.assertIsNotNone(row["candidate_object_type"])
            self.assertFalse(row["reviewed"])
            self.assertEqual(row["target_provenance"]["fine_depth"], "unavailable")
            self.assertEqual(row["object_materials"][3], 1)
            self.assertTrue(all(value is None for i, value in enumerate(row["object_materials"]) if i != 3))
            with np.load(root / "out" / row["targets"]) as maps:
                self.assertEqual(maps["material"][0, 0], 3)
                self.assertEqual(maps["material"][0, 1], 3)
                self.assertEqual(maps["material"][1, 1], 255)
                self.assertEqual(maps["material"][0, 2], 255)
                self.assertEqual(maps["metal_type"][0, 2], 255)
                self.assertTrue(np.isnan(maps["fine_depth"]).all())
                self.assertTrue(np.isnan(maps["boundary_x"]).all())
                self.assertTrue((maps["structure"] == 255).all())
                self.assertAlmostEqual(maps["base_depth"][1, 0], 1 - 16 / 255)
                self.assertAlmostEqual(maps["smoothness"][1, 0], 192 / 255)
                self.assertAlmostEqual(maps["dielectric_f0"][1, 0], 64 / 255)
                self.assertAlmostEqual(maps["ao"][1, 0], 128 / 255)

    def test_legacy_sanitization_and_reviewed_preservation(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            Image.fromarray(np.array([[[255, 0, 0, 255], [0, 0, 0, 0],
                                       [128, 128, 128, 255]]], dtype=np.uint8), "RGBA").save(root / "source.png")
            maps = {key: np.ones((1, 3), dtype=np.float32) for key in
                    ("material", "structure", "boundary_x", "boundary_y", "base_depth",
                     "fine_depth", "smoothness", "dielectric_f0", "metal_type", "ao")}
            maps["metal_type"][:] = [1, 255, 0]
            np.savez(root / "targets.npz", **maps)
            row = {"sample_id": "legacy", "source_artwork_id": "art", "mod_id": "mod",
                   "material_family": "family", "source": "source.png", "targets": "targets.npz",
                   "metadata": [0] * 64, "object_type": 1, "object_materials": [1] * 14,
                   "supervision_source": "exact_reference_pbr_pair", "reviewed": False}
            manifest = root / "rows.jsonl"
            manifest.write_text(json.dumps(row) + "\n" +
                                json.dumps({**row, "sample_id": "reviewed", "reviewed": True}) + "\n")
            data = ReviewedTextureDataset(root, manifest, material_classes=14,
                                          structure_classes=13, object_classes=15,
                                          metal_classes=10)
            legacy, reviewed = data[0], data[1]
            from integratepbr_engine.preprocess import LEGACY_ALPHA_PREPROCESS_VERSION
            old = ReviewedTextureDataset(root, manifest, material_classes=14,
                                         structure_classes=13, object_classes=15, metal_classes=10,
                                         preprocessing_version=LEGACY_ALPHA_PREPROCESS_VERSION)[0]
            np.testing.assert_array_equal(old["image"][[0, 1, 2, 4]], legacy["image"][[0, 1, 2, 4]])
            np.testing.assert_array_equal(old["image"][3], legacy["image"][3] / 255)
            self.assertEqual(float(legacy["image"][3, 0, 0]), 1.0)
            for name in legacy["targets"]:
                np.testing.assert_array_equal(old["targets"][name], legacy["targets"][name])
            self.assertEqual(tuple(old["image"].shape), (5, 1, 3))
            self.assertEqual(tuple(legacy["image"].shape), (5, 1, 3))
            old_batch = collate_native([old])
            current_batch = collate_native([legacy])
            padding = np.ones((8, 8), dtype=bool)
            padding[:1, :3] = False
            for sample, padded in ((old, old_batch), (legacy, current_batch)):
                self.assertEqual(tuple(padded["image"].shape), (1, 5, 8, 8))
                self.assertEqual(tuple(padded["valid"].shape), (1, 1, 8, 8))
                np.testing.assert_array_equal(padded["image"][0, :, :1, :3], sample["image"])
                np.testing.assert_array_equal(padded["valid"][0, 0, :1, :3], sample["image"][4])
                np.testing.assert_array_equal(padded["image"][:, 4:5], padded["valid"])
                self.assertTrue((padded["image"][0].numpy()[:, padding] == 0).all())
                self.assertTrue((padded["valid"][0, 0].numpy()[padding] == 0).all())
                for name in sample["targets"]:
                    np.testing.assert_array_equal(padded["targets"][name][0, :1, :3], sample["targets"][name])
            np.testing.assert_array_equal(old_batch["image"][:, [0, 1, 2, 4]], current_batch["image"][:, [0, 1, 2, 4]])
            np.testing.assert_array_equal(old_batch["image"][:, 3], current_batch["image"][:, 3] / 255)
            for name in old_batch["targets"]:
                np.testing.assert_array_equal(old_batch["targets"][name], current_batch["targets"][name])
            self.assertEqual(legacy["targets"]["material"].tolist(), [[3, 255, 255]])
            self.assertEqual(legacy["targets"]["structure"].tolist(), [[255, 255, 255]])
            self.assertTrue(np.isnan(legacy["targets"]["fine_depth"].numpy()).all())
            self.assertTrue(np.isnan(legacy["targets"]["boundary_x"].numpy()).all())
            self.assertEqual(int(legacy["object_type"]), -100)
            self.assertEqual(float(legacy["object_materials"][3]), 1)
            self.assertTrue(np.isnan(legacy["object_materials"][0]))
            self.assertEqual(int(reviewed["object_type"]), 1)
            self.assertEqual(reviewed["targets"]["structure"].tolist(), [[1, 1, 1]])
            batch = collate_native([legacy, reviewed])
            self.assertEqual(batch["reviewed"], [False, True])
            self.assertEqual(batch["supervision_source"], ["exact_reference_pbr_pair"] * 2)
            broken = dict(maps)
            broken.pop("metal_type")
            np.savez(root / "targets.npz", **broken)
            with self.assertRaisesRegex(ValueError, "metal_type is missing"):
                data[0]
            broken["metal_type"] = np.zeros((2, 3), dtype=np.float32)
            np.savez(root / "targets.npz", **broken)
            with self.assertRaisesRegex(ValueError, "does not align"):
                data[0]
            broken["metal_type"] = np.array([[10, 255, 0]], dtype=np.float32)
            np.savez(root / "targets.npz", **broken)
            with self.assertRaisesRegex(ValueError, "metal_type is outside the label table"):
                data[0]
            broken["metal_type"] = np.array([[1, 10, 255]], dtype=np.float32)
            np.savez(root / "targets.npz", **broken)
            self.assertEqual(data[0]["targets"]["metal_type"].tolist(), [[1, 255, 255]])
            manifest.write_text(json.dumps({**row, "supervision_source": "other"}) + "\n")
            with self.assertRaisesRegex(ValueError, "unreviewed samples"):
                ReviewedTextureDataset(root, manifest, material_classes=14,
                                       structure_classes=13, object_classes=15,
                                       metal_classes=10)

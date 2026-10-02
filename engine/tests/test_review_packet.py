"""Review packet integrity and sparse import tests."""

import json
import tempfile
import unittest
from pathlib import Path

import numpy as np
from PIL import Image

from integratepbr_engine.review import review_packet, import_review


class ReviewPacketTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.dataset = self.root / "dataset"
        self.training = self.root / "training"
        self.dataset.mkdir()
        (self.training / "old").mkdir(parents=True)
        self.rows = []
        for i in range(3):
            rgba = np.full((8, 8, 4), 255, dtype=np.uint8)
            rgba[0, 0, 0] = i
            Image.fromarray(rgba, "RGBA").save(self.dataset / f"{i}.png")
            maps = {key: np.full((8, 8), np.nan, dtype=np.float32) for key in
                    ("boundary_x", "boundary_y", "base_depth", "fine_depth",
                     "smoothness", "dielectric_f0", "ao")}
            maps.update(material=np.full((8, 8), 255, dtype=np.float32),
                        structure=np.full((8, 8), 255, dtype=np.float32),
                        metal_type=np.zeros((8, 8), dtype=np.float32))
            maps["base_depth"][:] = 0.25
            maps["smoothness"][:] = 0.5
            maps["metal_type"][0, 0] = 1
            np.savez(self.dataset / f"{i}.npz", **maps)
            self.rows.append({"sample_id": f"sample{i}", "source_artwork_id": f"art{i}",
                              "derivative_group": f"family{i}", "mod_id": "minecraft",
                              "material_family": "wood" if i == 0 else "masonry",
                              "source": f"{i}.png", "targets": f"{i}.npz",
                              "name": f"Planks {i}", "metadata": [0] * 64,
                              "object_type": None, "object_materials": [None] * 14,
                              "reviewed": False,
                              "supervision_source": "exact_reference_pbr_pair"})
        self.manifest = self.dataset / "validation.jsonl"
        self.manifest.write_text("".join(json.dumps(x) + "\n" for x in self.rows))
        (self.training / "old" / "train.jsonl").write_text(json.dumps(self.rows[2]) + "\n")
        self.packet = self.root / "packet"

    def test_packet_defaults_and_sparse_import(self):
        audit = review_packet(self.dataset, self.manifest, self.training, self.packet,
                              limit=2, seed=7)
        self.assertEqual((audit["eligible"], audit["known_lineage_overlap"]), (2, 1))
        self.assertEqual(audit["selected"], 2)
        self.assertEqual(audit["overlap_diagnostics"], 1)
        index = json.loads((self.packet / "index.json").read_text())
        self.assertEqual({x["sample_id"] for x in index["selected"]}, {"sample0", "sample1"})
        self.assertEqual(index["overlap_diagnostics"][0]["sample_id"], "sample2")
        self.assertTrue((self.packet / "contact-sheet.png").exists())
        with Image.open(self.packet / "previews/sample0.png") as preview:
            self.assertGreater(preview.width, 8)
        draft_path = self.packet / "drafts/sample0.json"
        draft = json.loads(draft_path.read_text())
        self.assertIsNone(draft["object_type"])
        self.assertEqual(draft["object_materials"], [None] * 14)
        with np.load(self.packet / "drafts/sample0.npz") as npz:
            self.assertTrue((npz["material"] == 255).all())
            self.assertTrue(np.isnan(npz["fine_depth"]).all())
        with self.assertRaises(FileExistsError):
            review_packet(self.dataset, self.manifest, self.training, self.packet)
        draft.update(review_status="approved", reviewer="Test Reviewer",
                     review_date="2026-09-30", annotation_version=2, object_type=1)
        draft_path.write_text(json.dumps(draft))
        output = self.root / "imported"
        report = import_review(self.packet, self.training, output)
        self.assertEqual(report["imported"], 1)
        imported = json.loads((output / "train.jsonl").read_text())
        self.assertTrue(imported["reviewed"])
        self.assertEqual(imported["object_type"], 1)
        self.assertEqual(imported["object_materials"][3], 1)
        self.assertIsNone(imported["object_materials"][0])
        self.assertEqual(imported["target_provenance"]["object_type"], "human_reviewed")
        self.assertNotEqual(imported["target_provenance"].get("structure"), "human_reviewed")
        self.assertNotEqual(imported["target_provenance"].get("boundary_x"), "human_reviewed")
        self.assertNotEqual(imported["target_provenance"].get("fine_depth"), "human_reviewed")
        with np.load(output / imported["targets"]) as npz:
            self.assertEqual(npz["metal_type"][0, 0], 1)
            self.assertEqual(npz["material"][0, 0], 3)
            self.assertEqual(npz["material"][1, 1], 255)
        with self.assertRaises(FileExistsError):
            import_review(self.packet, self.training, output)

    def test_metal_contradiction_and_boundary_only_review(self):
        review_packet(self.dataset, self.manifest, self.training, self.packet, limit=2)
        draft_path = self.packet / "drafts/sample0.json"
        draft = json.loads(draft_path.read_text())
        draft.update(review_status="approved", reviewer="Reviewer",
                     review_date="2026-09-30", annotation_version=2)
        draft["object_materials"][3] = 0
        draft_path.write_text(json.dumps(draft))
        with self.assertRaisesRegex(ValueError, "contradicts observed metal"):
            import_review(self.packet, self.training, self.root / "contradiction")
        draft["object_materials"][3] = None
        draft_path.write_text(json.dumps(draft))
        overlay_path = self.packet / "drafts/sample0.npz"
        with np.load(overlay_path) as npz:
            overlays = {key: np.array(npz[key]) for key in npz.files}
        overlays["boundary_x"][1, 1] = 1
        np.savez(overlay_path, **overlays)
        output = self.root / "boundary-only"
        import_review(self.packet, self.training, output)
        imported = json.loads((output / "train.jsonl").read_text())
        self.assertEqual(imported["target_provenance"]["boundary_x"], "human_reviewed")
        self.assertNotEqual(imported["target_provenance"].get("boundary_y"), "human_reviewed")
        self.assertEqual(imported["object_materials"][3], 1)

    def test_tamper_and_lineage_rejected(self):
        review_packet(self.dataset, self.manifest, self.training, self.packet, limit=2)
        draft_path = self.packet / "drafts/sample0.json"
        draft = json.loads(draft_path.read_text())
        draft.update(review_status="approved", reviewer="Reviewer",
                     review_date="2026-09-30", annotation_version=2, object_type=1)
        draft_path.write_text(json.dumps(draft))
        rgba = np.array(Image.open(self.dataset / "0.png"))
        rgba[7, 7, 1] = 0
        Image.fromarray(rgba, "RGBA").save(self.dataset / "0.png")
        with self.assertRaisesRegex(ValueError, "source integrity changed"):
            import_review(self.packet, self.training, self.root / "bad-source")
        Image.fromarray(np.full((8, 8, 4), 255, dtype=np.uint8), "RGBA").save(self.dataset / "0.png")
        (self.training / "old" / "train.jsonl").write_text(
            json.dumps(self.rows[2]) + "\n" + json.dumps(self.rows[0]) + "\n")
        with self.assertRaisesRegex(ValueError, "training manifest lineage changed"):
            import_review(self.packet, self.training, self.root / "bad-lineage")

    def test_measurement_and_label_hashes_rejected(self):
        review_packet(self.dataset, self.manifest, self.training, self.packet, limit=2)
        draft_path = self.packet / "drafts/sample0.json"
        draft = json.loads(draft_path.read_text())
        draft.update(review_status="approved", reviewer="Reviewer",
                     review_date="2026-09-30", annotation_version=2, object_type=1)
        draft_path.write_text(json.dumps(draft))
        index_path = self.packet / "index.json"
        index = json.loads(index_path.read_text())
        index["labels_sha256"] = "0" * 64
        index_path.write_text(json.dumps(index))
        with self.assertRaisesRegex(ValueError, "label vocabulary changed"):
            import_review(self.packet, self.training, self.root / "bad-labels")
        index["labels_sha256"] = __import__("hashlib").sha256(
            (Path(__file__).resolve().parents[2] / "contracts/labels.json").read_bytes()).hexdigest()
        index_path.write_text(json.dumps(index))
        with np.load(self.dataset / "0.npz") as npz:
            changed = {key: np.array(npz[key]) for key in npz.files}
        changed["base_depth"][:] = 0.75
        np.savez(self.dataset / "0.npz", **changed)
        with self.assertRaisesRegex(ValueError, "source target measurements changed"):
            import_review(self.packet, self.training, self.root / "bad-target")

    def test_invalid_identifier_and_shape(self):
        self.rows[0]["sample_id"] = "../unsafe"
        self.manifest.write_text("".join(json.dumps(x) + "\n" for x in self.rows))
        with self.assertRaisesRegex(ValueError, "invalid or duplicate sample IDs"):
            review_packet(self.dataset, self.manifest, self.training, self.packet)
        self.rows[0]["sample_id"] = "sample0"
        self.manifest.write_text("".join(json.dumps(x) + "\n" for x in self.rows))
        review_packet(self.dataset, self.manifest, self.training, self.packet, limit=2)
        draft_path = self.packet / "drafts/sample0.json"
        draft = json.loads(draft_path.read_text())
        draft.update(review_status="approved", reviewer="Reviewer",
                     review_date="2026-09-30", annotation_version=2, object_type=1)
        draft_path.write_text(json.dumps(draft))
        overlays = {key: np.full((8, 8), 255 if key in ("material", "structure") else np.nan)
                    for key in ("material", "structure", "boundary_x", "boundary_y", "fine_depth")}
        overlays["material"] = np.zeros((7, 8))
        np.savez(self.packet / "drafts/sample0.npz", **overlays)
        with self.assertRaisesRegex(ValueError, "invalid material shape"):
            import_review(self.packet, self.training, self.root / "bad-shape")

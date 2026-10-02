"""Small fixture checks for offline diagnostic selection, metrics, and rendering."""

import tempfile
import json
from unittest.mock import patch
import integratepbr_engine.diagnostics as diagnostics
import unittest
from pathlib import Path

import numpy as np
from PIL import Image

from integratepbr_engine.diagnostics import (CELL, HEADER, ROW, DEFAULT_IDS,
                                              _verify_inputs, choose_rows,
                                              make_door_preview, make_sheet, scalar_measure)


class DiagnosticTests(unittest.TestCase):
    def test_pinned_gates_allow_recorded_loader_difference(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder); weights=root/"model.safetensors"; weights.write_bytes(b"pinned fixture")
            labels=root/"labels.json"; labels.write_bytes(b"labels")
            source=root/"source.png"; source.write_bytes(b"source")
            target=root/"target.npz"; target.write_bytes(b"target")
            rows=[{"sample_id":sample_id,"source":"source.png","targets":"target.npz"} for sample_id in DEFAULT_IDS]
            manifest=root/"validation.jsonl"; manifest.write_text("\n".join(json.dumps(row) for row in rows),encoding="utf-8")
            repo=Path(diagnostics.__file__).resolve().parents[3]
            network=repo/"engine/src/integratepbr_engine/network.py"
            run={"model":{"sha256":diagnostics.sha256(weights),"bytes":weights.stat().st_size},"input_sha256":{"validation_manifest":diagnostics.sha256(manifest),"labels":diagnostics.sha256(labels),"assets":{"files":{"source.png":diagnostics.sha256(source),"target.npz":diagnostics.sha256(target)}}},"code_sha256":{"files":{"engine/src/integratepbr_engine/network.py":diagnostics.sha256(network),"engine/src/integratepbr_engine/dataset.py":"0"*64}}}
            runpath=root/"run-manifest.json"
            def save(): runpath.write_text(json.dumps(run),encoding="utf-8")
            save()
            with patch.object(diagnostics,"EXPECTED_WEIGHT_HASH",diagnostics.sha256(weights)),patch.object(diagnostics,"EXPECTED_WEIGHT_BYTES",weights.stat().st_size):
                selected,_,code=_verify_inputs(root,manifest,weights,labels,root/"output")
                self.assertEqual(len(selected),7)
                self.assertFalse(code["engine/src/integratepbr_engine/dataset.py"]["matches_training"])
                self.assertIsNone(code["engine/src/integratepbr_engine/preprocess.py"]["training_sha256"])
                run["code_sha256"]["files"]["engine/src/integratepbr_engine/network.py"]="0"*64; save()
                with self.assertRaisesRegex(ValueError,"network.py differs"): _verify_inputs(root,manifest,weights,labels,root/"output")
                weights.write_bytes(b"not pinned")
                with self.assertRaisesRegex(ValueError,"approved scratch checkpoint"): _verify_inputs(root,manifest,weights,labels,root/"output")
        code=Path(diagnostics.__file__).read_text(encoding="utf-8")
        self.assertIn("preprocessing_version=LEGACY_ALPHA_PREPROCESS_VERSION",code)
        self.assertIn("historical legacy checkpoint diagnosis",code)
        self.assertIn("current loader differs from the training snapshot",code)

    def test_no_overwrite_refuses_before_input_access(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "existing"
            output.mkdir()
            sentinel = output / "keep.txt"
            sentinel.write_text("untouched")
            with self.assertRaises(FileExistsError):
                _verify_inputs(Path(directory) / "missing", Path(directory) / "missing.jsonl",
                               Path(directory) / "missing.safetensors", Path(directory) / "missing-labels",
                               output)
            self.assertEqual(sentinel.read_text(), "untouched")

    def test_fixed_scale_masked_mae_and_zero_support(self):
        target = np.array([[0.0, 1.0], [np.nan, 0.5]], dtype=np.float32)
        prediction = np.array([[0.25, 0.0], [1.0, 0.0]], dtype=np.float32)
        valid = np.array([[True, False], [True, True]])
        measured = scalar_measure(target, prediction, valid)
        self.assertEqual(measured["support_pixels"], 2)
        self.assertAlmostEqual(measured["mae"], 0.375)
        self.assertIsNone(scalar_measure(target, prediction, np.zeros_like(valid))["mae"])

    def test_default_order_requires_manifest_membership(self):
        self.assertEqual(DEFAULT_IDS, (
            "ref-8cfea7ffb5830841-ad476ecb09", "ref-8d14467a3cb2953d-f1fc16dfcc",
            "ref-7969e7de5d7cf3fc-a228806e38", "ref-3c712c67186210ca-0039894e20",
            "ref-868e4a00cceb8e26-442802c1a6", "ref-932705109984973e-35a7bfcc94",
            "ref-1703566f6e4773cc-fc4673695a"))
        self.assertNotIn("ref-798f833c142424e5-ad420d8c73", DEFAULT_IDS)
        rows = [{"sample_id": value} for value in reversed(DEFAULT_IDS)]
        self.assertEqual([row["sample_id"] for row in choose_rows(rows)], list(DEFAULT_IDS))
        for door_id in DEFAULT_IDS[4:6]:
            with self.assertRaises(ValueError):
                choose_rows([row for row in rows if row["sample_id"] != door_id])
        with self.assertRaises(ValueError):
            choose_rows(rows + rows[:1])

    def test_door_preview_stacks_original_pixels_with_nearest_resize(self):
        top = Image.new("RGBA", (2, 2))
        bottom = Image.new("RGBA", (2, 2))
        top.putdata([(10, 20, 30, 255), (11, 21, 31, 255),
                     (12, 22, 32, 255), (13, 23, 33, 255)])
        bottom.putdata([(100, 110, 120, 255), (101, 111, 121, 255),
                        (102, 112, 122, 255), (103, 113, 123, 255)])
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "preview.png"
            info = make_door_preview(top, bottom, path, scale=4)
            self.assertEqual(info["native_dimensions"], {"width": 2, "height": 4})
            self.assertEqual(info["display_dimensions"], {"width": 8, "height": 16})
            with Image.open(path) as image:
                self.assertEqual(image.size, (8, 16))
                for x in range(8):
                    for y in range(16):
                        source = top if y < 8 else bottom
                        expected = source.getpixel((x // 4, (y % 8) // 4))
                        self.assertEqual(image.getpixel((x, y)), expected)

    def test_sheet_dimensions_and_columns(self):
        item = {"rgba": Image.new("RGBA", (2, 2), (30, 40, 50, 255)),
                "target": np.array([[0.0, 1.0], [np.nan, 0.5]]),
                "prediction": np.array([[0.0, 0.5], [0.0, 0.5]]),
                "mask": np.array([[True, True], [False, True]]), "label": "fixture"}
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "sheet.png"
            make_sheet("base_depth", [item], {}, path)
            with Image.open(path) as sheet:
                self.assertEqual(sheet.size, (4 * CELL, HEADER + ROW))
                self.assertEqual(sheet.getpixel((0, HEADER)), (30, 40, 50))
                self.assertEqual(sheet.getpixel((CELL, HEADER)), (0, 0, 0))
                self.assertEqual(sheet.getpixel((2 * CELL, HEADER)), (0, 0, 0))
                self.assertEqual(sheet.getpixel((3 * CELL, HEADER)), (0, 0, 0))
                self.assertEqual(sheet.getpixel((CELL, HEADER + CELL - 1)), (255, 0, 255))
                self.assertEqual(sheet.getpixel((2 * CELL - 1, HEADER + CELL - 1)), (128, 128, 128))


if __name__ == "__main__":
    unittest.main()

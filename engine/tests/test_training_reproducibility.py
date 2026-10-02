"""Focused preflight and provenance checks for scratch training."""

import argparse
import hashlib
import json
from unittest.mock import patch
import numpy as np
import torch
from PIL import Image
import tempfile
import unittest
from pathlib import Path

from integratepbr_engine.__main__ import _file_inventory, _train, _evaluate


class TrainingReproducibilityTests(unittest.TestCase):
    def test_output_must_be_new(self):
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder) / "existing"
            output.mkdir()
            with self.assertRaisesRegex(ValueError, "already exists"):
                _train(argparse.Namespace(output=output))

    def test_inventory_hashes_raw_bytes_in_path_order(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "b").write_bytes(b"second")
            (root / "a").write_bytes(b"first")
            inventory = _file_inventory([root / "b", root / "a"], root)
            self.assertEqual(inventory["files"]["a"], hashlib.sha256(b"first").hexdigest())
            records = "".join(f"{name}\t{digest}\n" for name, digest in
                              sorted(inventory["files"].items()))
            self.assertEqual(inventory["aggregate_sha256"],
                             hashlib.sha256(records.encode()).hexdigest())


class CompatibilityWiringTests(unittest.TestCase):
    def fixture(self, root):
        labels=root/"labels.json"
        labels.write_text(json.dumps({key:["unknown"] for key in ("materials","structures","objects","metals")}),encoding="utf-8")
        Image.fromarray(np.full((2,3,4),255,dtype=np.uint8)).save(root/"source.png")
        from integratepbr_engine.dataset import ReviewedTextureDataset
        maps={key:np.zeros((2,3),dtype=np.float32) for key in ReviewedTextureDataset.REQUIRED_TARGETS}
        np.savez(root/"target.npz",**maps)
        common={"mod_id":"fixture_mod","material_family":"fixture_family","source":"source.png","targets":"target.npz","sample_id":"fixture","metadata":[0]*64,"reviewed":True,"object_type":0,"object_materials":[0]}
        train=root/"train.jsonl"; valid=root/"valid.jsonl"
        train.write_text(json.dumps({**common,"source_artwork_id":"train"})+"\n",encoding="utf-8")
        valid.write_text(json.dumps({**common,"source_artwork_id":"valid"})+"\n",encoding="utf-8")
        return argparse.Namespace(output=root/"output",dataset_root=root,train_manifest=train,validation_manifest=valid,labels=labels,epochs=1,batch_size=1,learning_rate=0.001,seed=1,init_weights=None,cpu=True,manifest=valid,weights=root/"model.safetensors")

    def test_incompatible_rejected_before_loading_or_fit(self):
        with tempfile.TemporaryDirectory() as folder:
            args=self.fixture(Path(folder)); args.weights.write_bytes(b"bare"); args.init_weights=args.weights
            with patch("integratepbr_engine.network.ContextSwinUNet",return_value=torch.nn.Linear(1,1)),patch("safetensors.torch.load_file") as load,patch("integratepbr_engine.training.fit") as fit:
                for call in (_train,_evaluate):
                    with self.assertRaisesRegex(ValueError,"legacy incompatible"): call(args)
                load.assert_not_called(); fit.assert_not_called()

    def test_mocked_fit_final_stamping_and_inventory(self):
        with tempfile.TemporaryDirectory() as folder:
            args=self.fixture(Path(folder))
            def fake_fit(model,*loaders,**kwargs):
                output=kwargs["output_dir"]; output.mkdir()
                (output/"model.safetensors").write_bytes(b"fixture weights")
                (output/"model-metadata.json").write_text(json.dumps({"parameter_count":999,"schema_version":2,"architecture":"stale","weights_sha256":"stale","best_epoch":1,"validation_loss":0.2}),encoding="utf-8")
                return {"completed_epochs":1,"weight_decay":0.01,"early_stop_patience":5,"scheduler_patience":2,"best_epoch":1,"best_validation_loss":0.2}
            with patch("integratepbr_engine.network.ContextSwinUNet",return_value=torch.nn.Linear(1,1)),patch("integratepbr_engine.training.fit",side_effect=fake_fit):
                self.assertEqual(_train(args),0)
            from integratepbr_engine.model_package import validate_package
            metadata=validate_package(args.output/"model.safetensors",args.labels,parameter_count=2)
            self.assertEqual(metadata["run_manifest"],"run-manifest.json"); self.assertEqual(metadata["schema_version"],2)
            self.assertEqual(metadata["best_epoch"],1); self.assertEqual(metadata["validation_loss"],0.2)
            run=json.loads((args.output/"run-manifest.json").read_text(encoding="utf-8"))
            files=run["code_sha256"]["files"]
            repo=Path(__file__).resolve().parents[2]
            for name in ("preprocess.py","model_package.py"):
                key="engine/src/integratepbr_engine/"+name
                self.assertEqual(files[key],hashlib.sha256((repo/key).read_bytes()).hexdigest())
            self.assertEqual(run["training"]["preprocessing_version"],"rgba5-v2")

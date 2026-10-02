"""Mechanical offline execution tests; random weights are not quality evidence."""
import copy
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import numpy as np
from PIL import Image
import torch
from safetensors.torch import save_file
from integratepbr_engine.network import ContextSwinUNet, Prediction
from integratepbr_engine.model_package import create_metadata, sha256
from integratepbr_engine.pipeline import generate_job, _write_json, _validate_job
from integratepbr_engine.constraints import constrain_predictions, validate_predictions
from integratepbr_engine.labpbr import encode_labpbr, height_to_normal_xy

LABELS = Path(__file__).resolve().parents[2]/"contracts"/"labels.json"


class GenerationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        torch.set_num_threads(1)
        cls.temporary = tempfile.TemporaryDirectory()
        cls.root = Path(cls.temporary.name)
        cls.labels = json.loads(LABELS.read_text(encoding="utf-8"))
        torch.manual_seed(1234)
        cls.model = ContextSwinUNet(*(len(cls.labels[k]) for k in ("materials","structures","objects","metals")))
        cls.weights = cls.root/"model.safetensors"
        save_file(cls.model.state_dict(),str(cls.weights))
        cls.metadata = create_metadata(cls.weights,LABELS,sum(p.numel() for p in cls.model.parameters()),package_id="random-fixture",version="fixture-1",quality_status="random-test-fixture")
        _write_json(cls.root/"model-metadata.json",cls.metadata)
        cls.rgba = np.arange(5*11*4,dtype=np.uint8).reshape(5,11,4)
        cls.rgba[:,:,3] = 255
        cls.rgba[1:4,4,3] = 0
        cls.rgba[2,2,3] = 128
        Image.fromarray(cls.rgba).save(cls.root/"source.png")
        cls.job = {"protocol_version":1,"job_id":"fixture","resource_snapshot_id":"snapshot","input":{"resource_id":"fixture:item/edge","source_path":"source.png","sha256":sha256(cls.root/"source.png"),"width":11,"height":5,"alpha_mode":"translucent"},"context":{"owners":[],"evidence":[],"known_fields":[],"missing_fields":["metadata"],"attributes":{"surface_kind":"item_surface","topology":"bounded_plane","orientation":"x_right_y_down"}},"policy":{"policy_id":"offline-generic-experimental","version":"1"},"model_package":{k:cls.metadata[k] for k in ("package_id","version","architecture","preprocessing_version","weights_sha256","labels_sha256")},"output_dir":"output"}
    @classmethod
    def tearDownClass(cls): cls.temporary.cleanup()
    def setUp(self):
        self.job = copy.deepcopy(type(self).job)
        self.job["output_dir"] = "out-"+self._testMethodName
        self.path = self.root/(self._testMethodName+".json")
    def run_job(self):
        _write_json(self.path,self.job)
        return generate_job(self.path,self.root,self.weights,LABELS)
    def prediction(self,h=3,w=5):
        sizes = (len(self.labels["objects"]),len(self.labels["materials"]),len(self.labels["materials"]),len(self.labels["structures"]),2,1,1,1,1,len(self.labels["metals"]),1)
        values = [torch.zeros((1,c) if i<2 else (1,c,h,w)) for i,c in enumerate(sizes)]
        return Prediction(*values)
    def test_actual_cli_twice(self):
        outputs=[]
        for index in range(2):
            self.job["output_dir"] = f"real-{index}"
            _write_json(self.path,self.job)
            env=dict(os.environ,OMP_NUM_THREADS="1",MKL_NUM_THREADS="1")
            process=subprocess.run([sys.executable,"-m","integratepbr_engine","generate","--job",str(self.path),"--job-root",str(self.root),"--weights",str(self.weights),"--labels",str(LABELS)],capture_output=True,text=True,encoding="utf-8",env=env)
            self.assertEqual(process.returncode,0,process.stderr)
            result=json.loads(process.stdout)
            self.assertEqual(result["status"],"partial"); self.assertFalse(result["fallback"]["used"])
            out=self.root/self.job["output_dir"]; outputs.append(out)
            self.assertEqual(json.loads((out/"result.json").read_text(encoding="utf-8")),result)
            provenance=json.loads((out/"provenance.json").read_text(encoding="utf-8"))
            self.assertEqual(provenance["quality_status"],"random-test-fixture")
            self.assertEqual(provenance["padded_dimensions"],[16,8]); self.assertFalse(provenance["fine_depth_applied"])
            self.assertEqual(provenance["metadata"][-1],1)
            self.assertEqual(len(result["files"]),5)
            for entry in result["files"]:
                self.assertEqual(sha256(out/entry["path"]),entry["sha256"])
            albedo=out/"assets/fixture/textures/item/edge.png"
            self.assertEqual(albedo.read_bytes(),(self.root/"source.png").read_bytes())
            np.testing.assert_array_equal(np.asarray(Image.open(albedo)),self.rgba)
        for suffix in ("_n","_s"):
            self.assertEqual((outputs[0]/f"assets/fixture/textures/item/edge{suffix}.png").read_bytes(),(outputs[1]/f"assets/fixture/textures/item/edge{suffix}.png").read_bytes())
        with np.load(outputs[0]/"predictions.npz",allow_pickle=False) as first,np.load(outputs[1]/"predictions.npz",allow_pickle=False) as second:
            self.assertEqual(set(first.files),set(Prediction._fields))
            for key in first.files: np.testing.assert_array_equal(first[key],second[key])
    def test_suffix_resource_albedo_roles(self):
        for suffix in ("_n", "_s"):
            self.job["input"]["resource_id"] = "fixture:item/edge"+suffix
            self.job["output_dir"] = "suffix"+suffix
            result = self.run_job()
            self.assertEqual(result["status"], "partial", result.get("error"))
            out = self.root/self.job["output_dir"]
            albedo = out/("assets/fixture/textures/item/edge"+suffix+".png")
            self.assertEqual(albedo.read_bytes(), (self.root/"source.png").read_bytes())
            np.testing.assert_array_equal(np.asarray(Image.open(albedo)), self.rgba)
            self.assertEqual(next(e["role"] for e in result["files"] if e["path"] == albedo.relative_to(out).as_posix()), "albedo")
            with np.load(out/"predictions.npz", allow_pickle=False) as arrays:
                prediction = Prediction(*(torch.from_numpy(arrays[name])[None, None] if name in ("base_depth", "fine_depth", "smoothness", "dielectric_f0", "ao") else torch.from_numpy(arrays[name])[None] for name in Prediction._fields))
            expected = encode_labpbr(constrain_predictions(prediction,self.rgba[:,:,3]>0,self.labels),self.labels)
            for tag, pixels in zip(("_n", "_s"), expected):
                np.testing.assert_array_equal(np.asarray(Image.open(albedo.with_name(albedo.stem+tag+".png"))), pixels)
    def test_owners_transport_shape(self):
        self.job["context"]["owners"] = ["not_namespaced"]
        with patch.object(ContextSwinUNet,"forward") as forward:
            self.assertEqual(self.run_job()["status"],"failed")
            forward.assert_not_called()
        for owners in ([], ["fixture:item/example.png"]):
            self.job["context"]["owners"] = owners
            _validate_job(self.job)
    def test_embedded_apng_skips_before_model(self):
        apng = self.root/"animated.png"
        second = self.rgba.copy(); second[:,:,0] ^= 255
        Image.fromarray(self.rgba).save(apng,save_all=True,append_images=[Image.fromarray(second)],duration=100,loop=0)
        self.job["input"].update(source_path="animated.png",sha256=sha256(apng))
        with patch("integratepbr_engine.pipeline.load_file") as loader, patch.object(ContextSwinUNet,"forward") as forward:
            result = self.run_job()
            self.assertEqual(result["status"],"skipped")
            self.assertIn("embedded",result["checks"][0]["detail"])
            self.assertEqual(result["files"],[]); self.assertFalse(result["fallback"]["used"])
            loader.assert_not_called(); forward.assert_not_called()
        self.assertFalse((self.root/self.job["output_dir"]).exists())
        self.assertEqual(list(self.root.glob(".integratepbr-stage-*")),[])
    def test_constraints_metal_gates_and_quantization(self):
        pred=self.prediction()
        pred.object_type[0,1]=20; pred.object_materials[0,self.labels["materials"].index("metal")]=20
        pred.material[:,self.labels["materials"].index("metal")]=20; pred.metal_type[:,1]=20
        pred.base_depth.fill_(1); pred.dielectric_f0.fill_(1); pred.smoothness.fill_(2); pred.ao.fill_(-1)
        original=pred.base_depth.clone()
        valid=np.ones((3,5),bool); valid[1,2]=False
        result=constrain_predictions(pred,valid,self.labels,max_depth_alpha=1.9)
        self.assertTrue(np.all(result["height"][valid]==254)); self.assertFalse(result["fine_depth_applied"])
        n,s=encode_labpbr(result,self.labels)
        self.assertTrue(np.all(s[:,:,1][valid]==230)); np.testing.assert_array_equal(n[1,2],[128,128,255,255])
        for head in ("object_type","object_materials","material"):
            changed=Prediction(*(v.clone() for v in pred))
            if head=="object_type": changed.object_type[0,0]=40
            elif head=="object_materials": changed.object_materials.fill_(-20)
            else: changed.material.fill_(0)
            constrained=constrain_predictions(changed,valid,self.labels)
            self.assertTrue(np.all(constrained["metal_indices"]==0))
            _,spec=encode_labpbr(constrained,self.labels); self.assertTrue(np.all(spec[:,:,1][valid]==229))
        mixed=Prediction(*(v.clone() for v in pred)); mixed.material[:,:,0,0]=0
        self.assertEqual(constrain_predictions(mixed,valid,self.labels)["metal_indices"][0,0],0)
        for index,name in enumerate(self.labels["metals"]):
            changed=Prediction(*(v.clone() for v in pred)); changed.metal_type.fill_(-20); changed.metal_type[:,index]=20
            _,spec=encode_labpbr(constrain_predictions(changed,valid,self.labels),self.labels)
            self.assertEqual(int(spec[0,0,1]),229 if name=="none" else self.labels["metal_labpbr_green"][name])
        pred.base_depth[0,0,0]=torch.tensor([0,0.5/255,1/255,1.999/255,2/255])
        result=constrain_predictions(pred,valid,self.labels)
        np.testing.assert_array_equal(result["depth_byte"][0],[0,0,1,1,2])
        self.assertTrue(torch.equal(original[1:],pred.base_depth[1:]))
    def test_normals_spacing_and_gaps(self):
        valid=np.ones((5,9),bool)
        self.assertTrue(np.all(height_to_normal_xy(np.full((5,9),255),valid,du=1/9,dv=1/5)==0))
        ramp=np.tile(np.arange(9),(5,1))+240
        xy=height_to_normal_xy(ramp,valid,du=1/9,dv=1/5)
        self.assertLess(xy[2,4,0],0); self.assertEqual(xy[2,4,1],0)
        ramp_y=np.tile(np.arange(5)[:,None],(1,9))+240
        self.assertLess(height_to_normal_xy(ramp_y,valid,du=1/9,dv=1/5)[2,4,1],0)
        isolated=np.zeros((5,9),bool); isolated[2,4]=True
        self.assertTrue(np.all(height_to_normal_xy(ramp,isolated,du=1/9,dv=1/5)==0))
        valid[:,4]=False; ramp[:,5:]=0
        self.assertEqual(height_to_normal_xy(ramp,valid,du=1/9,dv=1/5)[2,5,0],0)
        small=np.tile(np.linspace(200,240,5),(5,1)); large=np.tile(np.linspace(200,240,9),(9,1))
        np.testing.assert_allclose(height_to_normal_xy(small,np.ones_like(small,bool),du=1/4,dv=1/4)[2,2],height_to_normal_xy(large,np.ones_like(large,bool),du=1/8,dv=1/8)[4,4])
    def test_invalid_job_fields(self):
        for field,value in (("source_path","../source.png"),("source_path","a\\b.png"),("resource_id","a:../bad"),("resource_id","a:path.png"),("width",True),("sha256","bad"),("height",6)):
            with self.subTest(field=field):
                self.job=copy.deepcopy(type(self).job); self.job["input"][field]=value
                self.assertEqual(self.run_job()["status"],"failed")
        for policy in ({"policy_id":"bad","version":"1"},{"policy_id":"offline-generic-experimental","version":1},{"policy_id":"offline-generic-experimental","version":"1","overrides":{"max_depth_alpha":True}},{"policy_id":"offline-generic-experimental","version":"1","overrides":{"unknown":1}}):
            self.job=copy.deepcopy(type(self).job); self.job["policy"]=policy
            self.assertEqual(self.run_job()["status"],"failed")
        for metadata in ([0]*63,[True]*64,[0]*32+[float("nan")]+[0]*31,[0]*63+[0.5]):
            self.job=copy.deepcopy(type(self).job); self.job["context"]["attributes"]["metadata"]=metadata
            with self.assertRaises(ValueError): _validate_job(self.job)
    def test_skipped_profiles(self):
        for key,value in (("topology","tiled"),("orientation","rotated"),("surface_kind","entity")):
            self.job=copy.deepcopy(type(self).job); self.job["context"]["attributes"][key]=value
            result=self.run_job(); self.assertEqual(result["status"],"skipped"); self.assertEqual(result["files"],[])
        self.job=copy.deepcopy(type(self).job); self.job["input"]["animation"]={"frame_width":11,"frame_height":5,"frames":[{"index":0,"time":1}],"interpolate":False}
        self.assertEqual(self.run_job()["status"],"skipped")
        self.job=copy.deepcopy(type(self).job)
        side=self.root/"source.png.mcmeta"; side.write_text("{}",encoding="utf-8")
        try: self.assertEqual(self.run_job()["status"],"skipped")
        finally: side.unlink()
        transparent=self.rgba.copy(); transparent[:,:,3]=0
        Image.fromarray(transparent).save(self.root/"transparent.png")
        self.job["input"].update(source_path="transparent.png",sha256=sha256(self.root/"transparent.png"))
        self.assertEqual(self.run_job()["status"],"skipped")
    def test_existing_output_and_symlink(self):
        output=self.root/self.job["output_dir"]; output.mkdir()
        self.assertEqual(self.run_job()["status"],"failed")
        output.rmdir()
        with tempfile.TemporaryDirectory() as outside:
            link=self.root/"escape"
            try: link.symlink_to(outside,target_is_directory=True)
            except OSError as exc: self.skipTest("OS denied symlink creation: "+str(exc))
            try:
                self.job["output_dir"]="escape/out"
                self.assertEqual(self.run_job()["status"],"failed")
            finally: link.unlink()
    def test_package_identity_failures_before_forward(self):
        path=self.root/"model-metadata.json"
        for key,value in (("preprocessing_version",None),("preprocessing_version","rgba5-legacy-alpha-v1"),("package_id","other"),("weights_sha256","0"*64),("parameter_count",1)):
            changed=dict(self.metadata)
            if value is None: changed.pop(key)
            else: changed[key]=value
            _write_json(path,changed)
            try:
                with patch.object(ContextSwinUNet,"forward",side_effect=AssertionError("forward forbidden")) as forward:
                    self.assertEqual(self.run_job()["status"],"failed"); forward.assert_not_called()
            finally: _write_json(path,self.metadata)
        with patch("integratepbr_engine.pipeline.load_file",return_value={}):
            with patch.object(ContextSwinUNet,"forward") as forward:
                self.assertEqual(self.run_job()["status"],"failed"); forward.assert_not_called()
    def test_all_prediction_heads_reject_nonfinite_and_shapes(self):
        for name in Prediction._fields:
            with self.subTest(head=name):
                pred=self.prediction(); getattr(pred,name).reshape(-1)[0]=float("nan")
                with self.assertRaises(ValueError): validate_predictions(pred,self.labels,3,5)
                pred=self.prediction(); pred=pred._replace(**{name:getattr(pred,name)[..., :0]})
                with self.assertRaises(ValueError): validate_predictions(pred,self.labels,3,5)
        with patch.object(ContextSwinUNet,"forward",return_value=self.prediction()):
            self.assertEqual(self.run_job()["error"]["code"],"PREDICTION_INVALID")
    def test_write_and_check_failures_clean_owned_stage(self):
        for target in ("_write_json","_check_artifacts"):
            _write_json(self.path,self.job)
            with patch("integratepbr_engine.pipeline."+target,side_effect=OSError("injected failure")):
                result=generate_job(self.path,self.root,self.weights,LABELS)
            self.assertEqual(result["status"],"failed"); self.assertEqual(result["files"],[])
            self.assertFalse((self.root/self.job["output_dir"]).exists())
            self.assertEqual(list(self.root.glob(".integratepbr-stage-*")),[])
            self.assertTrue(self.weights.exists()); self.assertTrue((self.root/"source.png").exists())

if __name__ == "__main__": unittest.main()

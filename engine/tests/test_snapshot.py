"""Consumes real Java export; no handwritten substitute or accepted quality claim."""
import copy
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import hashlib
import numpy as np
from PIL import Image
import torch
from safetensors.torch import save_file
from integratepbr_engine.snapshot import validate_snapshot, prepare_snapshot, canonical, identity, SCOPE, LABELS
from integratepbr_engine.model_package import create_metadata,sha256
from integratepbr_engine.pipeline import _write_json
from integratepbr_engine.network import ContextSwinUNet


class SnapshotTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        value=os.environ.get("INTEGRATEPBR_SNAPSHOT_FIXTURE")
        if not value: raise RuntimeError("INTEGRATEPBR_SNAPSHOT_FIXTURE must be produced by real Java resourceSnapshotRegression")
        cls.fixture=Path(value)
        cls.manifest,cls.decoded=validate_snapshot(cls.fixture)
        cls.temp=tempfile.TemporaryDirectory();cls.root=Path(cls.temp.name)
        torch.set_num_threads(1);torch.manual_seed(1234)
        labels=json.loads(LABELS.read_text(encoding="utf-8"))
        model=ContextSwinUNet(*(len(labels[k]) for k in ("materials","structures","objects","metals")))
        cls.weights=cls.root/"model.safetensors";save_file(model.state_dict(),str(cls.weights))
        cls.package=cls.root/"model-metadata.json"
        _write_json(cls.package,create_metadata(cls.weights,LABELS,sum(p.numel() for p in model.parameters()),package_id="random-fixture",version="fixture-1",quality_status="random-test-fixture"))
    @classmethod
    def tearDownClass(cls): cls.temp.cleanup()
    def setUp(self):
        self.work=Path(tempfile.mkdtemp(dir=self.root));self.snapshot=self.work/"snapshot";shutil.copytree(self.fixture,self.snapshot)
        self.manifest=copy.deepcopy(type(self).manifest)
    def save(self):
        self.manifest["snapshot_id"]=identity(self.manifest);_write_json(self.snapshot/"manifest.json",self.manifest)
    def declarations(self):
        path=self.work/"declarations.json"
        _write_json(path,{"schema_version":1,"snapshot_id":self.manifest["snapshot_id"],"declarations":[{"resource_id":t["resource_id"],"source_sha256":t["source"]["sha256"],"surface_kind":"item_surface","topology":"bounded_plane","orientation":"x_right_y_down","scope":SCOPE} for t in self.manifest["textures"] if t["source"]]})
        return path
    def test_java_identity_and_default_unknown(self):
        golden={"a":1,"provider":"caf\u00e9","context":{"renderer":"unknown"}}
        self.assertEqual(canonical({"a":1}),b"O1:S1:aI1;")
        self.assertEqual(hashlib.sha256(canonical(golden)).hexdigest(),"23b8ce05d5081402e33c9be5c8989a56f1471662547f472b20c5fa985db52d0e")
        self.assertEqual(identity(self.manifest),self.manifest["snapshot_id"])
        with patch.object(ContextSwinUNet,"forward") as forward:
            report=prepare_snapshot(self.snapshot,self.work/"default")
            self.assertEqual(report["jobs"],[]);forward.assert_not_called()
        for row in report["coverage"]:
            self.assertEqual(row["usage"]["status"],"unresolved");self.assertIsNone(row["usage"]["selected_profile"])
            self.assertIn("package_missing",row["reasons"])
    def test_real_cross_language_cli_twice(self):
        declaration=self.declarations();outputs=[];reports=[];jobs=[]
        for index in range(2):
            prepared=self.work/f"prepared-{index}"
            env=dict(os.environ,OMP_NUM_THREADS="1",MKL_NUM_THREADS="1")
            command=[sys.executable,"-m","integratepbr_engine","prepare-snapshot","--snapshot-root",str(self.snapshot),"--output-root",str(prepared),"--package-metadata",str(self.package),"--declarations",str(declaration),"--experimental-offline-plane"]
            run=subprocess.run(command,capture_output=True,text=True,encoding="utf-8",env=env)
            self.assertEqual(run.returncode,0,run.stderr);report=json.loads(run.stdout);reports.append(report)
            self.assertEqual(len(report["jobs"]),1)
            row=report["coverage"][0];self.assertEqual(row["usage"]["status"],"unresolved");self.assertEqual(row["decision"],"prepared")
            jobpath=prepared/report["jobs"][0]["job_path"];jobs.append(jobpath.read_bytes());job=json.loads(jobs[-1])
            self.assertEqual(job["input"]["resource_id"],"minecraft:item/edge_n")
            features=job["context"]["attributes"]["metadata"];self.assertEqual([i for i,v in enumerate(features) if v],[1,63])
            result_run=subprocess.run([sys.executable,"-m","integratepbr_engine","generate","--job",str(jobpath),"--job-root",str(prepared),"--weights",str(self.weights),"--labels",str(LABELS)],capture_output=True,text=True,encoding="utf-8",env=env)
            self.assertEqual(result_run.returncode,0,result_run.stderr);result=json.loads(result_run.stdout);self.assertEqual(result["status"],"partial")
            output=prepared/job["output_dir"];outputs.append(output)
            albedo=output/"assets/minecraft/textures/item/edge_n.png";source=self.snapshot/self.manifest["textures"][0]["source"]["source_path"]
            self.assertEqual(albedo.read_bytes(),source.read_bytes());np.testing.assert_array_equal(np.asarray(Image.open(albedo)),np.asarray(Image.open(source)))
            provenance=json.loads((output/"provenance.json").read_text(encoding="utf-8"));self.assertEqual(provenance["job"]["resource_snapshot_id"],self.manifest["snapshot_id"]);self.assertEqual(provenance["job"]["context"]["evidence"][0]["value"]["geometry"]["evidence_level"],"offline_json_geometry")
            self.assertEqual(provenance["job"]["context"]["evidence"][1]["value"]["scope"],SCOPE)
            self.assertEqual(provenance["job"]["context"]["owners"],sorted({o["id"] for o in self.manifest["textures"][0]["owners"]}))
        self.assertEqual(reports[0],reports[1]);self.assertEqual(jobs[0],jobs[1])
        for name in ("edge_n_n.png","edge_n_s.png"):
            self.assertEqual((outputs[0]/"assets/minecraft/textures/item"/name).read_bytes(),(outputs[1]/"assets/minecraft/textures/item"/name).read_bytes())
        with np.load(outputs[0]/"predictions.npz",allow_pickle=False) as a,np.load(outputs[1]/"predictions.npz",allow_pickle=False) as b:
            for name in a.files:np.testing.assert_array_equal(a[name],b[name])
    def test_v2_documents_and_v1_compatibility(self):
        self.assertEqual(self.manifest["schema_version"],2)
        report=prepare_snapshot(self.snapshot,self.work/"geometry-default",self.package)
        geometry=report["geometry"];self.assertFalse(geometry["runtime_verified"])
        base=next(u for u in geometry["uses"] if u["owner"]["id"]=="registry_alias:sample" and u["branch"]["kind"]=="item_base")
        self.assertEqual(len(base["faces"]),6);self.assertTrue(base["dependency_complete"])
        north=next(f for f in base["faces"] if f["direction"]=="north")
        self.assertEqual(north["uv"],[15.5,13.25,-1,2.5]);self.assertEqual(north["rotation"],90)
        self.assertEqual(north["source_document"]["resource_id"],"fixture:models/parent.json")
        self.assertEqual(north["runtime_tint"],"unknown");self.assertEqual(north["tintindex"],2)
        generated=next(u for u in geometry["uses"] if u["family"]=="generated_layers")
        self.assertTrue(generated["dependency_complete"]);self.assertIn("generated_side_geometry_unknown",generated["unsupported_reasons"])
        old=copy.deepcopy(self.manifest);old.pop("source_documents");old["schema_version"]=1;old["snapshot_id"]=identity(old)
        _write_json(self.snapshot/"manifest.json",old);validate_snapshot(self.snapshot)
        compatibility=prepare_snapshot(self.snapshot,self.work/"v1")
        self.assertEqual(compatibility["geometry"]["evidence_level"],"geometry_evidence_unavailable")
    def test_document_preflight_opens_zero_and_normal_once(self):
        original=copy.deepcopy(self.manifest)
        docpaths={str((self.snapshot/d["source_path"]).resolve()) for d in original["source_documents"]}
        actual_open=Path.open
        opened=[]
        def count(path,*args,**kwargs):
            if str(path.resolve()) in docpaths:opened.append(str(path.resolve()))
            return actual_open(path,*args,**kwargs)
        with patch.object(Path,"open",count):validate_snapshot(self.snapshot)
        self.assertEqual(len(opened),len(docpaths));self.assertEqual(len(set(opened)),len(opened))
        for mode in ("duplicate","aggregate","kind"):
            self.manifest=copy.deepcopy(original)
            if mode=="duplicate":self.manifest["source_documents"].append(copy.deepcopy(self.manifest["source_documents"][0]))
            elif mode=="kind":self.manifest["source_documents"][0]["kind"]=[]
            else:
                base=self.manifest["source_documents"][0];records=[]
                for index in range(33):
                    rid=f"fixture:models/budget{index:02d}.json"
                    records.append(dict(base,resource_id=rid,source_path="assets/fixture/"+rid.split(":")[1],byte_count=262144))
                self.manifest["source_documents"]=records
            self.save();opened.clear()
            with patch.object(Path,"open",count):
                with self.assertRaises(ValueError):validate_snapshot(self.snapshot)
            self.assertEqual(opened,[])
        self.manifest=original;self.save()
        missing=self.snapshot/original["source_documents"][0]["source_path"];missing.unlink()
        with self.assertRaisesRegex(ValueError,"missing captured document"):validate_snapshot(self.snapshot)
    def test_actual_block_conditional_evidence(self):
        report=prepare_snapshot(self.snapshot,self.work/"block-evidence",self.package)
        self.assertEqual(report["jobs"],[])
        shared=next(row for row in report["coverage"] if row["resource_id"]=="minecraft:textures/zz/geometry_shared.png")
        self.assertEqual(shared["decision"],"conflict");self.assertTrue(shared["owner_use_conflict"])
        block=[u for u in report["geometry"]["uses"] if u["owner"]=={"kind":"block","id":"fixture:geometry_block"}]
        self.assertEqual(len(block),3);self.assertEqual(len({u["use_id"] for u in block}),3)
        variant=next(u for u in block if u["branch"]["kind"]=="variant" and u["branch"]["index"]==0)
        self.assertEqual((variant["branch"]["x"],variant["branch"]["y"],variant["branch"]["uvlock"],variant["branch"]["weight"]),(90,180,True,2))
        multipart=next(u for u in block if u["branch"]["kind"]=="multipart")
        self.assertEqual(multipart["branch"]["when"],{"OR":[{"powered":"true"},{"facing":"south"}]})
        self.assertEqual(multipart["root_provenance"]["source_pack_id"],"fixture-json")
        self.assertEqual(multipart["root_provenance"]["sha256"],next(d["sha256"] for d in self.manifest["source_documents"] if d["resource_id"]=="fixture:blockstates/geometry_block.json"))
        self.assertTrue(all(u["dependency_complete"] and not u["runtime_verified"] for u in block))
    def test_v2_document_transport_corruption(self):
        document=self.manifest["source_documents"][0];path=self.snapshot/document["source_path"];raw=path.read_bytes()
        path.write_bytes(raw+b"x")
        with self.assertRaises(ValueError):validate_snapshot(self.snapshot)
        path.write_bytes(raw)
        for field,value in (("kind","wrong"),("source_path","../bad"),("sha256","0"*64),("byte_count",True)):
            original=copy.deepcopy(self.manifest);self.manifest["source_documents"][0][field]=value;self.save()
            with self.assertRaises(ValueError):validate_snapshot(self.snapshot)
            self.manifest=original;self.save()
    def test_required_nullable_fields(self):
        texture=self.manifest["textures"][0]
        self.assertIsNone(texture["sidecar"])
        self.assertEqual(texture["companions"],{"normal":None,"specular":None})
        validate_snapshot(self.snapshot)
        original=copy.deepcopy(self.manifest)
        for key in ("sidecar","normal","specular"):
            self.manifest=copy.deepcopy(original)
            target=self.manifest["textures"][0] if key=="sidecar" else self.manifest["textures"][0]["companions"]
            target.pop(key);self.save()
            with self.assertRaisesRegex(ValueError,"closed snapshot record"):validate_snapshot(self.snapshot)
            self.manifest=copy.deepcopy(original);self.save()
    def test_corruption_rejected(self):
        original=copy.deepcopy(self.manifest)
        for mutate in (lambda m:m.update(schema_version=True),lambda m:m.update(snapshot_id="0"*64),lambda m:m["textures"].append(copy.deepcopy(m["textures"][0])),lambda m:m["textures"][0].update(width=12),lambda m:m["textures"][0]["source"].update(byte_count=0),lambda m:m["textures"][0]["source"].update(source_path="../escape.png"),lambda m:m.update(unknown=1)):
            self.manifest=copy.deepcopy(original);mutate(self.manifest);_write_json(self.snapshot/"manifest.json",self.manifest)
            with self.assertRaises(ValueError):validate_snapshot(self.snapshot)
        self.manifest=original;_write_json(self.snapshot/"manifest.json",original)
        source=self.snapshot/original["textures"][0]["source"]["source_path"];raw=source.read_bytes();source.write_bytes(raw+b"x")
        with self.assertRaises(ValueError):validate_snapshot(self.snapshot)
        source.write_bytes(raw)
        path=self.snapshot/"manifest.json";text=path.read_text(encoding="utf-8")
        needle='"schema_version": '+str(original["schema_version"])
        self.assertEqual(text.count(needle),1)
        changed=text.replace(needle,needle+", "+needle,1)
        self.assertNotEqual(changed,text)
        path.write_text(changed,encoding="utf-8")
        with self.assertRaisesRegex(ValueError,"duplicate JSON key"):validate_snapshot(self.snapshot)
    def test_declaration_package_and_collision(self):
        declarations=self.declarations()
        with self.assertRaises(ValueError):prepare_snapshot(self.snapshot,self.work/"no-opt",self.package,declarations)
        original=json.loads(declarations.read_text(encoding="utf-8"))
        for change in (lambda d:d.update(snapshot_id="0"*64),lambda d:d["declarations"].append(copy.deepcopy(d["declarations"][0])),lambda d:d["declarations"][0].update(source_sha256="0"*64),lambda d:d["declarations"][0].update(resource_id="fixture:textures/unknown.png")):
            d=copy.deepcopy(original);change(d);_write_json(declarations,d)
            with self.assertRaises(ValueError):prepare_snapshot(self.snapshot,self.work/"bad",self.package,declarations,experimental=True)
        _write_json(declarations,original)
        incompatible=self.work/"legacy.json";_write_json(incompatible,{"preprocessing_version":"legacy"})
        report=prepare_snapshot(self.snapshot,self.work/"legacy",incompatible,declarations,experimental=True)
        self.assertEqual(report["jobs"],[]);self.assertIn("package_incompatible",report["coverage"][0]["reasons"])
        with self.assertRaises(ValueError):prepare_snapshot(self.snapshot,self.work/"legacy")
        with patch("integratepbr_engine.snapshot._write_json",side_effect=OSError("injected")):
            with self.assertRaises(OSError):prepare_snapshot(self.snapshot,self.work/"failed",self.package,declarations,experimental=True)
        self.assertFalse((self.work/"failed").exists());self.assertEqual(list(self.work.glob(".integratepbr-prepared-*")),[])
    def test_mixed_incomplete_armor_and_animation(self):
        original=copy.deepcopy(self.manifest)
        for reason in ("owner_use_conflict","shared_scope_incomplete","armor_candidate_unverified","animation_unsupported"):
            self.manifest=copy.deepcopy(original);texture=self.manifest["textures"][0]
            if reason=="owner_use_conflict": texture["owners"].append({"kind":"block","id":"fixture:shared"});texture["owners"].sort(key=canonical)
            elif reason=="shared_scope_incomplete": self.manifest["discovery"]["shared_scope_complete"]=False
            elif reason=="armor_candidate_unverified":
                for e in texture["evidence"]:e["kind"]="armor_filename_candidate"
                texture["evidence"].sort(key=canonical)
            else:
                source=texture["source"];side=dict(source,resource_id=texture["resource_id"]+".mcmeta",source_path=source["source_path"]+".mcmeta",source_pack_id="sidecar-provider")
                sidepath=self.snapshot/side["source_path"];sidepath.write_bytes(b"malformed");side.update(sha256=sha256(sidepath),byte_count=sidepath.stat().st_size);texture["sidecar"]=side
            self.save();report=prepare_snapshot(self.snapshot,self.work/reason,self.package,self.declarations(),experimental=True)
            self.assertEqual(report["jobs"],[]);self.assertIn(reason,report["coverage"][0]["reasons"])
    def test_malformed_metadata_is_incompatible(self):
        declaration=self.declarations()
        malformed=(b"{",b"\xff",b'{"a":1,"a":2}',b'{"number":NaN}',b"[]",b'{"package_schema_version":true}',b'{"preprocessing_version":"legacy"}',b"x"*2097153)
        for index,raw in enumerate(malformed):
            path=self.work/f"metadata-{index}.json";path.write_bytes(raw)
            with patch.object(ContextSwinUNet,"forward") as forward:
                report=prepare_snapshot(self.snapshot,self.work/f"malformed-{index}",path,declaration,experimental=True)
                self.assertEqual(report["jobs"],[]);self.assertIn("package_incompatible",report["coverage"][0]["reasons"]);forward.assert_not_called()
        with self.assertRaises(FileNotFoundError):prepare_snapshot(self.snapshot,self.work/"missing-package",self.work/"missing.json",declaration,experimental=True)
        self.assertFalse((self.work/"missing-package").exists())
    def test_whole_metadata_provenance_safety(self):
        declaration=self.declarations()
        valid=json.loads(self.package.read_text(encoding="utf-8"))
        encoded=json.dumps(valid)
        extras=('"extra":1e999','"extra":{"nested":[1e999]}','"extra":"\\ud800"','"extra":{"\\ud800":"key"}')
        for index,extra in enumerate(extras):
            path=self.work/f"unsafe-provenance-{index}.json"
            path.write_text(encoded[:-1]+","+extra+"}",encoding="utf-8")
            out=self.work/f"unsafe-report-{index}"
            with patch.object(ContextSwinUNet,"forward") as forward:
                report=prepare_snapshot(self.snapshot,out,path,declaration,experimental=True)
                self.assertEqual(report["jobs"],[]);self.assertIsNone(report["package"])
                self.assertIn("package_incompatible",report["coverage"][0]["reasons"]);forward.assert_not_called()
            self.assertEqual(json.loads((out/"report.json").read_text(encoding="utf-8")),report)
        safe=dict(valid,extra={"finite":0.125,"unicode":"caf\u00e9","values":[True,None,17]})
        path=self.work/"safe-provenance.json";_write_json(path,safe)
        with patch.object(ContextSwinUNet,"forward") as forward:
            report=prepare_snapshot(self.snapshot,self.work/"safe-report",path,declaration,experimental=True)
            self.assertEqual(report["package"],safe);self.assertEqual(len(report["jobs"]),1);forward.assert_not_called()
    def test_external_pbr_and_embedded_animation_ineligible(self):
        texture=self.manifest["textures"][0];source=texture["source"]
        companion=dict(source,resource_id=texture["resource_id"][:-4]+"_n.png",source_path=source["source_path"][:-4]+"_n.png",source_pack_id="independent-normal")
        path=self.snapshot/companion["source_path"];path.write_bytes((self.snapshot/source["source_path"]).read_bytes())
        companion.update(sha256=sha256(path),byte_count=path.stat().st_size);texture["companions"]["normal"]=companion;self.save()
        report=prepare_snapshot(self.snapshot,self.work/"external",self.package,self.declarations(),experimental=True)
        self.assertEqual(report["jobs"],[]);self.assertIn("external_pbr_present",report["coverage"][0]["reasons"])
        texture["companions"]["normal"]=None
        sourcepath=self.snapshot/source["source_path"]
        image=Image.open(sourcepath).convert("RGBA");other=np.asarray(image).copy();other[:,:,0]^=255
        image.save(sourcepath,save_all=True,append_images=[Image.fromarray(other)],duration=100,loop=0)
        source.update(sha256=sha256(sourcepath),byte_count=sourcepath.stat().st_size);self.save()
        report=prepare_snapshot(self.snapshot,self.work/"apng",self.package,self.declarations(),experimental=True)
        self.assertEqual(report["jobs"],[]);self.assertIn("animation_unsupported",report["coverage"][0]["reasons"])
    def test_resolved_symlink_escape(self):
        source=self.snapshot/self.manifest["textures"][0]["source"]["source_path"]
        external=self.work/"outside.png";external.write_bytes(source.read_bytes());source.unlink()
        try:source.symlink_to(external)
        except OSError as exc:
            if getattr(exc,"winerror",None)==1314:self.skipTest("Windows symlink privilege WinError1314")
            raise
        with self.assertRaises(ValueError):validate_snapshot(self.snapshot)

if __name__=="__main__":unittest.main()

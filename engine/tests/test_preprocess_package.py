"""Native preprocessing, fail-closed packages and transport shape checks."""
import copy
import json
import re
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import numpy as np
from integratepbr_engine.preprocess import preprocess_rgba, CURRENT_PREPROCESS_VERSION as CURRENT, LEGACY_ALPHA_PREPROCESS_VERSION as LEGACY
from integratepbr_engine.model_package import create_metadata, validate_package, sha256

class FoundationTests(unittest.TestCase):
    def test_native_channels_and_legacy(self):
        rgba=np.arange(24,dtype=np.uint8).reshape(2,3,4)
        rgba[:,:,3]=[0,128,255]
        original=rgba.copy()
        current=preprocess_rgba(rgba,version=CURRENT)
        legacy=preprocess_rgba(rgba,version=LEGACY)
        self.assertEqual(current.shape,(2,3,5)); self.assertEqual(current.dtype,np.float32)
        np.testing.assert_array_equal(rgba,original)
        np.testing.assert_array_equal(current[:,:,:4],rgba.astype(np.float32)/255)
        np.testing.assert_array_equal(current[:,:,4],[[0,1,1],[0,1,1]])
        np.testing.assert_array_equal(legacy[:,:,3],current[:,:,3]/255)
        np.testing.assert_array_equal(legacy[:,:,[0,1,2,4]],current[:,:,[0,1,2,4]])

    def test_invalid_input(self):
        for value in [[],np.zeros((2,3,4)),np.zeros((2,3),dtype=np.uint8),np.zeros((2,3,3),dtype=np.uint8)]:
            with self.subTest(value=type(value)),self.assertRaises(ValueError): preprocess_rgba(value,version=CURRENT)
        with self.assertRaises(ValueError): preprocess_rgba(np.zeros((2,3,4),dtype=np.uint8),version="unknown")

    def test_package_roundtrip_and_rejections(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder); weights=root/"model.safetensors"; labels=root/"labels.json"; meta=root/"model-metadata.json"
            weights.write_bytes(b"fixture"); labels.write_bytes(b"labels")
            identity=create_metadata(weights,labels,42,best_epoch=2,architecture="stale",weights_sha256="stale")
            self.assertEqual(identity["best_epoch"],2); self.assertEqual(identity["parameter_count"],42)
            self.assertEqual(identity["weights_sha256"],sha256(weights)); self.assertEqual(identity["labels_sha256"],sha256(labels))
            def write(value): meta.write_text(json.dumps(value),encoding="utf-8")
            write(identity); self.assertEqual(validate_package(weights,labels,parameter_count=42),identity)
            variants=[[],None,{},{k:v for k,v in identity.items() if k!="preprocessing_version"}]
            for key in identity:
                if key=="best_epoch": continue
                variants.append({k:v for k,v in identity.items() if k!=key})
            for key,values in {"package_schema_version":[True,2,"1"],"parameter_count":[True,0,1.5,"42"],"architecture":[False,"old"],"preprocessing_version":[False,LEGACY],"labels_sha256":["A"*64,"0"*64,False],"weights_sha256":["bad","0"*64,False],"weights_file":["../model.safetensors","..\\model.safetensors","/model.safetensors","C:model.safetensors","C:/model.safetensors","\\\\host\\model.safetensors",".","..",False,"other.safetensors"]}.items():
                variants.extend({**identity,key:value} for value in values)
            for value in variants:
                with self.subTest(metadata=value):
                    write(value)
                    with self.assertRaises(ValueError): validate_package(weights,labels)
            write(identity)
            with self.assertRaises(ValueError): validate_package(weights,labels,parameter_count=43)
            weights.write_bytes(b"tamper")
            with self.assertRaises(ValueError): validate_package(weights,labels)
            meta.unlink()
            with self.assertRaisesRegex(ValueError,"legacy incompatible"): validate_package(weights,labels)
            meta.write_text("{",encoding="utf-8")
            with self.assertRaises(ValueError): validate_package(weights,labels)

    def test_structural_errors_precede_hash_reads(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder); weights=root/"model.safetensors"; meta=root/"model-metadata.json"
            metadata={"package_schema_version":1,"architecture":"context_swin_unet_v2","preprocessing_version":CURRENT,"labels_sha256":"0"*64,"weights_sha256":"0"*64,"weights_file":"../bad","parameter_count":1}
            meta.write_text(json.dumps(metadata),encoding="utf-8")
            with patch("integratepbr_engine.model_package.sha256") as hasher:
                with self.assertRaises(ValueError): validate_package(weights,root/"absent")
                hasher.assert_not_called()

    def test_schema_structure(self):
        root=Path(__file__).resolve().parents[2]/"contracts"
        schemas=[json.loads((root/f"generation-{name}.v1.schema.json").read_text(encoding="utf-8")) for name in ("job","result")]
        for schema in schemas:
            self.assertEqual(schema["$schema"],"https://json-schema.org/draft/2020-12/schema")
            self.assertFalse(schema["additionalProperties"])
            self.assertEqual(schema["properties"]["protocol_version"],{"type":"integer","const":1})
            def walk(value):
                if isinstance(value,dict):
                    if "$ref" in value:
                        self.assertTrue(value["$ref"].startswith("#/$defs/")); self.assertIn(value["$ref"].split("/")[-1],schema["$defs"])
                    for item in value.values(): walk(item)
                elif isinstance(value,list):
                    for item in value: walk(item)
            walk(schema)
            path=re.compile(schema["$defs"]["relative_path"]["pattern"])
            for value in ["a/b.png","task/output"]: self.assertIsNotNone(path.fullmatch(value))
            for value in ["","/a","a//b","a/../b","./a","a/.","a/","C:a","a\\b","//host/a"]: self.assertIsNone(path.fullmatch(value),value)
            digest=re.compile(schema["$defs"]["sha256"]["pattern"])
            self.assertIsNotNone(digest.fullmatch("a"*64)); self.assertIsNone(digest.fullmatch("A"*64))
        job,result=schemas
        self.assertEqual(set(job["required"]),{"protocol_version","job_id","resource_snapshot_id","input","context","policy","model_package","output_dir"})
        for key in ["input","context","policy","model_package","animation","frame","evidence"]: self.assertFalse(job["$defs"][key]["additionalProperties"])
        self.assertEqual(job["$defs"]["input"]["properties"]["width"]["minimum"],1)
        self.assertEqual(set(job["$defs"]["input"]["required"]),{"resource_id","source_path","sha256","width","height"})
        self.assertEqual(set(job["$defs"]["context"]["required"]),{"owners","evidence","known_fields","missing_fields"})
        self.assertTrue(job["$defs"]["context"]["properties"]["attributes"]["additionalProperties"])
        self.assertTrue(job["$defs"]["policy"]["properties"]["overrides"]["additionalProperties"])
        self.assertEqual(result["properties"]["status"]["enum"],["queued","preprocessing","understanding","segmenting","generating","checking","encoding","completed","partial","skipped","failed","cancelled"])
        self.assertEqual(result["if"]["properties"]["status"]["const"],"failed"); self.assertEqual(result["then"]["required"],["error"])
        for key in ["file","check","fallback","timing","error"]: self.assertFalse(result["$defs"][key]["additionalProperties"])
        self.assertNotIn("minItems",result["properties"]["files"])

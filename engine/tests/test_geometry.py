"""Pure source semantics plus mandatory real Java-v2 fixture checks."""
import copy
import json
import os
from pathlib import Path
import unittest
from integratepbr_engine.geometry import resolve_geometry,default_uv
from integratepbr_engine.snapshot import validate_snapshot


class GeometryTests(unittest.TestCase):
    def resolve(self,models,kind="item",owner="fixture:root"):
        docs={key:json.dumps(value,ensure_ascii=True).encode() if not isinstance(value,bytes) else value for key,value in models.items()}
        manifest={"schema_version":2,"selected_owner":{"kind":kind,"id":owner},"textures":[],"source_documents":[{"resource_id":key,"source_pack_id":"fixture","sha256":"0"*64} for key in docs]}
        return resolve_geometry(manifest,docs)
    def model(self,**extra):
        return {"textures":{"base":"fixture:block/a","alias":"#base","particle":"fixture:block/unused"},"elements":[{"from":[1.5,2.25,3.5],"to":[12.5,14.25,9.5],"faces":{d:{"texture":"alias"} for d in ("down","up","north","south","west","east")}}],**extra}
    def test_real_java_v2(self):
        fixture=os.environ.get("INTEGRATEPBR_SNAPSHOT_FIXTURE")
        if not fixture:raise RuntimeError("mandatory actual Java fixture missing")
        root=Path(fixture);manifest,_=validate_snapshot(root)
        self.assertEqual(manifest["schema_version"],2)
        docs={d["resource_id"]:(root/d["source_path"]).read_bytes() for d in manifest["source_documents"]}
        result=resolve_geometry(manifest,docs);self.assertFalse(result["runtime_verified"]);self.assertFalse(result["diagnostics"])
        base=next(u for u in result["uses"] if u["owner"]["id"]=="registry_alias:sample" and u["branch"]["kind"]=="item_base")
        self.assertEqual(len(base["faces"]),6);self.assertEqual(base["elements"][0]["from"],[1.5,2.25,3.5])
        override=next(u for u in result["uses"] if u["branch"]["kind"]=="item_override" and u["branch"]["index"]==0)
        self.assertEqual(override["branch"]["predicate"],{"custom:state":0.25});self.assertEqual(len(override["faces"]),1)
    def test_six_default_formulas_and_rotations(self):
        expected={"down":[1.5,6.5,12.5,12.5],"up":[1.5,3.5,12.5,9.5],"north":[3.5,1.75,14.5,13.75],"south":[1.5,1.75,12.5,13.75],"west":[3.5,1.75,9.5,13.75],"east":[6.5,1.75,12.5,13.75]}
        result=self.resolve({"fixture:models/item/root.json":self.model()})
        for face in result["uses"][0]["faces"]:self.assertEqual(face["uv"],expected[face["direction"]])
        for angle in (0,90,180,270):
            model=self.model();model["elements"][0]["faces"]={"north":{"texture":"#alias","uv":[18,-2,-3,15],"rotation":angle,"tintindex":1}}
            face=self.resolve({"fixture:models/item/root.json":model})["uses"][0]["faces"][0]
            corners=[[18,-2],[18,15],[-3,15],[-3,-2]]
            self.assertEqual(face["uv_corners"],[corners[(i+angle//90)%4] for i in range(4)])
            self.assertFalse(face["runtime_verified"]);self.assertEqual(face["runtime_tint"],"unknown")
    def test_inheritance_and_face_keys(self):
        parent=self.model();child={"parent":"fixture:parent","textures":{"base":"other:block/replaced"},"elements":[]}
        result=self.resolve({"fixture:models/item/root.json":child,"fixture:models/parent.json":parent})
        self.assertTrue(all(f["texture_resource_id"]=="other:textures/block/replaced.png" for f in result["uses"][0]["faces"]))
        self.assertEqual(len(result["uses"][0]["faces"]),6)
        child["elements"]=[{"from":[0,0,0],"to":[2,3,4],"faces":{"up":{"texture":"base"}}}]
        self.assertEqual(len(self.resolve({"fixture:models/item/root.json":child,"fixture:models/parent.json":parent})["uses"][0]["faces"]),1)
        child["elements"][0]["faces"]["up"]["texture"]="fixture:block/direct"
        self.assertFalse(self.resolve({"fixture:models/item/root.json":child,"fixture:models/parent.json":parent})["uses"][0]["dependency_complete"])
    def test_generated_entity_custom_and_incomplete(self):
        root={"parent":"other:builtin/generated","textures":{"layer0":"fixture:item/a","layer2":"fixture:item/b"},"elements":self.model()["elements"]}
        use=self.resolve({"fixture:models/item/root.json":root})["uses"][0]
        self.assertEqual(use["family"],"generated_layers");self.assertEqual(len(use["generated_layers"]),1);self.assertTrue(use["dependency_complete"]);self.assertEqual(use["faces"],[])
        for key,value in (("parent","builtin/entity"),("loader","custom:loader"),("transform",{}),("visibility",{})):
            model=self.model();model[key]=value;use=self.resolve({"fixture:models/item/root.json":model})["uses"][0]
            self.assertTrue(use["dependency_complete"]);self.assertTrue(use["unsupported_reasons"]);self.assertEqual(use["faces"],[])
        for raw in (b'{"x":1,"x":2}',b'{"x":1e999}',b'{"x":"\\ud800"}',b'['*66+b'0'+b']'*66):
            result=self.resolve({"fixture:models/item/root.json":raw});self.assertTrue(result["diagnostics"]);self.assertFalse(result["uses"][0]["dependency_complete"])
        root={"parent":"fixture:cycle"};other={"parent":"fixture:item/root"}
        self.assertFalse(self.resolve({"fixture:models/item/root.json":root,"fixture:models/cycle.json":other})["uses"][0]["dependency_complete"])
    def test_immediate_element_face_global_budgets(self):
        element={"from":[0,0,0],"to":[1,1,1],"faces":{"up":{"texture":"base"}}}
        for size in (512,513):
            model={"textures":{"base":"fixture:a"},"elements":[copy.deepcopy(element) for _ in range(size)]}
            use=self.resolve({"fixture:models/item/root.json":model})["uses"][0]
            self.assertEqual(len(use["elements"]),512);self.assertEqual(len(use["faces"]),512)
            self.assertEqual(use["dependency_complete"],size==512)
        model={"textures":{"base":"fixture:a"},"elements":[copy.deepcopy(element) for _ in range(512)]}
        variants=[{"model":"fixture:shape"} for _ in range(17)]
        report=self.resolve({"fixture:blockstates/root.json":{"variants":{"":variants}},"fixture:models/shape.json":model},kind="block")
        self.assertEqual(sum(len(u["elements"]) for u in report["uses"]),8192)
        self.assertEqual(sum(len(u["faces"]) for u in report["uses"]),8192)
        self.assertFalse(all(u["dependency_complete"] for u in report["uses"]))
        model=self.model();model["elements"][0]["faces"]={d:{"texture":"base"} for d in ("down","up","north","south","west","east")};model["elements"]*=86
        use=self.resolve({"fixture:models/item/root.json":model})["uses"][0]
        self.assertEqual(len(use["faces"]),512);self.assertLessEqual(len(use["elements"]),86);self.assertFalse(use["dependency_complete"])
    def test_overflow_fields_and_invalid_branches(self):
        model=self.model();model["elements"][0]["from"][0]=10**400
        result=self.resolve({"fixture:models/item/root.json":model})
        self.assertFalse(result["uses"][0]["dependency_complete"])
        for mutate in (lambda m:m["elements"][0].update(rotation={"origin":[0,0,0],"axis":"x","angle":12}),lambda m:m["elements"][0]["faces"]["up"].update(rotation=True),lambda m:m["elements"][0]["faces"]["up"].update(tintindex=True),lambda m:m["elements"][0]["faces"].update(wrong={"texture":"base"})):
            model=self.model();mutate(model);self.assertFalse(self.resolve({"fixture:models/item/root.json":model})["uses"][0]["dependency_complete"])
        state={"variants":{"empty":[],"invalid":{"model":"fixture:shape","x":True},"valid":{"model":"fixture:shape"}},"multipart":[{"when":[],"apply":{"model":"fixture:shape"}},{"apply":[]}]}
        report=self.resolve({"fixture:blockstates/root.json":state,"fixture:models/shape.json":self.model()},kind="block")
        self.assertEqual(len(report["uses"]),1);self.assertGreaterEqual(len(report["diagnostics"]),4)
    def test_conditional_blocks_and_own_overrides(self):
        model=self.model()
        state={"variants":{"facing=north":[{"model":"fixture:shape","x":90,"y":180,"uvlock":True,"weight":2},{"model":"fixture:shape"}]},"multipart":[{"when":{"OR":[{"a":"true"},{"b":"false"}]},"apply":{"model":"fixture:shape"}}]}
        result=self.resolve({"fixture:blockstates/root.json":state,"fixture:models/shape.json":model},kind="block")
        self.assertEqual(len(result["uses"]),3);self.assertEqual(len({u["use_id"] for u in result["uses"]}),3)
        self.assertTrue(all(u["dependency_complete"] for u in result["uses"]));self.assertTrue(any("blockstate_transform_unbaked" in u["unsupported_reasons"] for u in result["uses"]))
        parent=self.model(overrides=[{"predicate":{"a":1},"model":"fixture:unused"}])
        child={"parent":"fixture:parent"}
        result=self.resolve({"fixture:models/item/root.json":child,"fixture:models/parent.json":parent})
        self.assertEqual(len(result["uses"]),1)
        bad=self.model();bad["elements"][0]["from"][0]=True
        self.assertFalse(self.resolve({"fixture:models/item/root.json":bad})["uses"][0]["dependency_complete"])

if __name__=="__main__":unittest.main()

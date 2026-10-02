"""Actual Java-exported v3 transports, with independent float32 decoding checks."""
import copy
import hashlib
import json
import os
from pathlib import Path
import shutil
import struct
import tempfile
import unittest
from integratepbr_engine.runtime_observation import parse_runtime_observation
from integratepbr_engine.snapshot import prepare_snapshot,validate_snapshot,identity

class RuntimeObservationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        location=os.environ.get('INTEGRATEPBR_RUNTIME_FIXTURE')
        if not location:raise AssertionError('INTEGRATEPBR_RUNTIME_FIXTURE required: real Java exporter only')
        cls.root=Path(location)
        cls.item_manifest=json.loads((cls.root/'item/manifest.json').read_text(encoding='utf-8'))
        cls.raw=(cls.root/'item/observations/runtime.json').read_bytes()
        cls.value=json.loads(cls.raw)
        cls.owner=cls.item_manifest['selected_owner']
    def parse(self,value):return parse_runtime_observation(json.dumps(value,separators=(',',':'),ensure_ascii=False).encode(),self.owner)
    def test_actual_item_block_and_no_source_reports(self):
        for role in ('item','block','empty'):
            with self.subTest(role=role),tempfile.TemporaryDirectory() as temporary:
                manifest,_=validate_snapshot(self.root/role)
                report=prepare_snapshot(self.root/role,Path(temporary)/'prepare')
                observed=report['runtime_observation']
                self.assertEqual(observed['origin'],'test_fixture');self.assertEqual(observed['evidence_level'],'synthetic_baked_model_query')
                self.assertEqual(observed['status'],'complete');self.assertFalse(observed['rendered_frame_verified']);self.assertEqual(observed['source_mapping'],'unknown')
                self.assertEqual(observed['selected_query_usage'],manifest['selected_owner']['kind']);self.assertEqual(len(observed['queries']),14)
                self.assertTrue(observed['sprite_groups']);self.assertEqual(report['jobs'],[])
                if role=='empty':self.assertEqual(manifest['textures'],[]);self.assertTrue(observed['quads'])
    def test_independent_float32_tint_and_handles(self):
        value=parse_runtime_observation(self.raw,self.owner)
        self.assertEqual(len(value['models']),3)
        self.assertEqual([value['context']['item'][k] for k in ('base_model_handle','resolved_model_handle','transformed_model_handle')],[0,1,2])
        quad=value['quads'][0];sprite=value['sprites'][0]
        self.assertEqual(quad['tint']['raw_color'],0x55667788)
        expected_uv=[(.35,.3),(.15,.7),(.15,.3),(.35,.7)]
        f32=lambda n:struct.unpack('f',struct.pack('f',n))[0]
        for v,(u,w) in enumerate(expected_uv):
            decoded=quad['decoded_vertices'][v]
            self.assertEqual(decoded['position'],[v+.25,-v-.5,.125]);self.assertEqual(decoded['vertex_color'],0x10203040)
            self.assertEqual(decoded['atlas_uv'],[f32(u),f32(w)])
            self.assertEqual(quad['local_sprite_uv'][v],[(f32(u)-.125)/.25,(f32(w)-.25)/.5])
        self.assertEqual([q['bucket'] for q in value['queries'][:7]],['down','up','north','south','west','east',None]);self.assertTrue(all(q['seed']==42 for q in value['queries']))
    def test_strict_corruptions(self):
        mutations=[lambda v:v.update(extra=True),lambda v:v.update(origin='fake'),lambda v:v['context'].update(rendered_frame_verified=True),lambda v:v['models'][0].update(handle=True),lambda v:v['queries'][0].update(model_handle=999),lambda v:v['queries'][0].update(seed=43),lambda v:v['quads'][0]['decoded_vertices'][0]['position'].__setitem__(0,3),lambda v:v['quads'][0]['local_sprite_uv'][0].__setitem__(0,3),lambda v:v['quads'][0].update(packed_vertex_count=33),lambda v:v['quads'][0]['tint'].update(raw_color=True),lambda v:v['sprites'][0].update(u1=.125),lambda v:v['context']['item'].update(stack_encoding_sha256='0'*64),lambda v:v['queries'][0].update(quad_indices=[]),lambda v:v['context']['item'].update(stack_count=True)]
        for mutation in mutations:
            v=copy.deepcopy(self.value);mutation(v)
            with self.assertRaises(ValueError):self.parse(v)
        for raw in (self.raw.replace(b'"schema_version":1',b'"schema_version":1,"schema_version":1',1),self.raw.replace(b'0.125',b'1e999',1),b'{"x":"\\ud800"}',b'['*40+b']'*40,b'NaN',b'\xff',b' '*4194305):
            with self.assertRaises(ValueError):parse_runtime_observation(raw,self.owner)
    def test_incomplete_raw_nan_bits_and_live_claim_label(self):
        v=copy.deepcopy(self.value);v['status']='incomplete';q=v['quads'][0];q.update(status='incomplete',decoded_vertices=None,local_sprite_uv=None);q['packed_vertices'][0]=0x7fc00000;q['omission_codes']=['invalid_vertex'];v['queries'][0].update(status='incomplete',omission_codes=['invalid_vertex']);v['omissions']=[{'code':'invalid_vertex','detail':'fixture'}]
        self.assertEqual(self.parse(v)['status'],'incomplete')
        v['origin']='client_runtime_query';self.assertEqual(self.parse(v)['evidence_level'],'live_baked_model_query')
    def test_transport_corruptions_and_byte_identity(self):
        for field,value in [('source_path','../runtime.json'),('sha256','0'*64),('byte_count',4194305),('byte_count',1),('observation_schema_version',True)]:
            with tempfile.TemporaryDirectory() as temporary:
                target=Path(temporary)/'copy';shutil.copytree(self.root/'item',target);m=copy.deepcopy(self.item_manifest);m['runtime_observation'][field]=value;m['snapshot_id']=identity(m);(target/'manifest.json').write_text(json.dumps(m),encoding='utf-8')
                with self.assertRaises(ValueError):validate_snapshot(target)
        with tempfile.TemporaryDirectory() as temporary:
            target=Path(temporary)/'copy';shutil.copytree(self.root/'item',target);m=copy.deepcopy(self.item_manifest);raw=self.raw+b'\n';(target/'observations/runtime.json').write_bytes(raw);m['runtime_observation'].update(sha256=hashlib.sha256(raw).hexdigest(),byte_count=len(raw));m['snapshot_id']=identity(m);self.assertNotEqual(m['snapshot_id'],self.item_manifest['snapshot_id']);(target/'manifest.json').write_text(json.dumps(m),encoding='utf-8');validate_snapshot(target)
    def test_v2_remains_unqueried(self):
        source=os.environ.get('INTEGRATEPBR_SNAPSHOT_FIXTURE');self.assertTrue(source)
        with tempfile.TemporaryDirectory() as temporary:self.assertIsNone(prepare_snapshot(Path(source),Path(temporary)/'prepare')['runtime_observation'])

    def test_raw_component_identity_and_false_complete(self):
        v=copy.deepcopy(self.value);arm=v['context']['item']
        raw=arm['stack_encoding_json'];self.assertIn('E-4',raw);self.assertIn('雪',raw)
        self.assertEqual(hashlib.sha256(raw.encode()).hexdigest(),arm['stack_encoding_sha256'])
        self.assertEqual(arm['stack_encoding']['fraction'],.0001)
        mutations=[lambda v:v['context']['item'].update(stack_encoding_json=v['context']['item']['stack_encoding_json']+' '),lambda v:v['context']['item']['stack_encoding'].update(count=True),lambda v:v['context']['item'].update(pose_matrix=None),lambda v:v['context']['item'].update(left_hand=True),lambda v:v['context']['item'].update(model_seed=1),lambda v:v['context']['item'].update(display_context='GUI'),lambda v:v['quads'][0].update(query_id=False),lambda v:v['quads'][0].update(tint_index=-1),lambda v:v['quads'][0].update(omission_codes=['error']),lambda v:v['queries'][0].update(omission_codes=['error']),lambda v:v['quads'][0]['tint'].update(status='incomplete',raw_color=None,error_code='failure'),lambda v:v['sprites'][0].update(sprite_id='bad'),lambda v:v['context'].update(dimension_id='../bad')]
        for mutation in mutations:
            x=copy.deepcopy(v);mutation(x)
            with self.assertRaises(ValueError):self.parse(x)
        x=copy.deepcopy(v);encoded=x['context']['item']['stack_encoding'];spelling=json.dumps(encoded,ensure_ascii=True,separators=(',',':'));x['context']['item'].update(stack_encoding_json=spelling,stack_encoding_sha256=hashlib.sha256(spelling.encode()).hexdigest());self.parse(x)
        schema=json.loads((Path(__file__).resolve().parents[2]/'contracts/runtime-observation.v1.schema.json').read_text(encoding='utf-8'))
        self.assertIn('stack_encoding_json',schema['properties']['context']['properties']['item']['anyOf'][0]['required']);self.assertIn('tint_index',schema['properties']['quads']['items']['required'])
    def test_actual_partial_java_transports(self):
        for role in ('oversized_packed','bad_sibling','negative_tint','untinted','tint_error','null_type','transform_error','unsafe_encoding','deep_encoding','node_limit','byte_limit','property_limit'):
            m,_=validate_snapshot(self.root/role);raw=(self.root/role/'observations/runtime.json').read_bytes();v=parse_runtime_observation(raw,m['selected_owner'])
            self.assertEqual(v['status'],'complete' if role in ('negative_tint','untinted') else 'incomplete')
            if role=='oversized_packed':self.assertIsNone(v['quads'][0]['packed_vertices']);self.assertEqual(v['quads'][0]['packed_vertex_count'],1000000)
            if role=='bad_sibling':self.assertEqual(len(v['quads']),28)
            if role=='negative_tint':self.assertEqual(v['quads'][0]['tint_index'],-2);self.assertEqual(v['quads'][0]['tint']['status'],'sampled')
            if role=='untinted':self.assertEqual(v['quads'][0]['tint_index'],-1);self.assertIsNone(v['quads'][0]['tint']['raw_color'])
            if role=='transform_error':self.assertEqual(v['context']['item']['base_model_handle'],0);self.assertEqual(v['context']['item']['resolved_model_handle'],1)
            if role=='node_limit':self.assertEqual(v['quads'],[]);self.assertEqual(v['omissions'][0]['code'],'observation_structure_limit')
            if role=='property_limit':self.assertEqual(len(v['context']['block']['state_properties']),64)
        m=json.loads((self.root/'block/manifest.json').read_text(encoding='utf-8'));v=json.loads((self.root/'block/observations/runtime.json').read_bytes());v['context']['block']['input_model_data_empty']=None
        with self.assertRaises(ValueError):parse_runtime_observation(json.dumps(v).encode(),m['selected_owner'])
    def test_declared_v3_provenance_without_forward(self):
        import torch
        from safetensors.torch import save_file
        from unittest.mock import patch
        from integratepbr_engine.network import ContextSwinUNet
        from integratepbr_engine.model_package import create_metadata
        from integratepbr_engine.snapshot import LABELS,SCOPE
        with tempfile.TemporaryDirectory() as temporary:
            work=Path(temporary);torch.manual_seed(1234);labels=json.loads(LABELS.read_text(encoding='utf-8'));model=ContextSwinUNet(*(len(labels[k]) for k in ('materials','structures','objects','metals')));weights=work/'model.safetensors';save_file(model.state_dict(),str(weights));metadata=work/'model-metadata.json';metadata.write_text(json.dumps(create_metadata(weights,LABELS,sum(p.numel() for p in model.parameters()),package_id='random-fixture',version='fixture-1')),encoding='utf-8')
            for role in ('item','negative_tint','null_type'):
                m=json.loads((self.root/role/'manifest.json').read_text(encoding='utf-8'));declarations=work/(role+'-declarations.json');declarations.write_text(json.dumps({'schema_version':1,'snapshot_id':m['snapshot_id'],'declarations':[{'resource_id':t['resource_id'],'source_sha256':t['source']['sha256'],'surface_kind':'item_surface','topology':'bounded_plane','orientation':'x_right_y_down','scope':SCOPE} for t in m['textures'] if t['source']]}),encoding='utf-8')
                with patch.object(ContextSwinUNet,'forward') as forward:report=prepare_snapshot(self.root/role,work/role,metadata,declarations,experimental=True);forward.assert_not_called()
                self.assertEqual(len(report['jobs']),1);job=json.loads((work/role/report['jobs'][0]['job_path']).read_text(encoding='utf-8'));self.assertEqual(job['context']['evidence'][0]['value']['runtime_observation'],report['runtime_observation']);self.assertFalse(report['runtime_observation']['rendered_frame_verified']);self.assertEqual(report['coverage'][1]['decision'],'conflict')

    def test_actual_malformed_normalization_and_corruption(self):
        for role in ('null_packed_sibling','empty_property'):
            m,_=validate_snapshot(self.root/role);v=parse_runtime_observation((self.root/role/'observations/runtime.json').read_bytes(),m['selected_owner']);self.assertEqual(v['status'],'incomplete')
            if role=='null_packed_sibling':
                self.assertEqual(len(v['quads']),28);self.assertTrue(all(q['status']=='incomplete' and len(q['quad_indices'])==2 for q in v['queries']));self.assertTrue(any(o['code']=='missing_packed_vertices' for o in v['omissions']))
                raw=json.loads((self.root/role/'observations/runtime.json').read_bytes());raw['quads'][0].update(packed_vertices=None,packed_vertex_count=0,status='incomplete',decoded_vertices=None,local_sprite_uv=None)
            else:
                self.assertEqual(v['context']['block']['state_properties'],{'valid':'named'});self.assertTrue(any(o['code']=='state_property_limit' for o in v['omissions']));raw=json.loads((self.root/role/'observations/runtime.json').read_bytes());raw['context']['block']['state_properties']['empty']=''
            with self.assertRaises(ValueError):parse_runtime_observation(json.dumps(raw).encode(),m['selected_owner'])

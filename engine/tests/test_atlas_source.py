"""Real Java-exported current recipes/pixels; no competing Python recipe replay."""
import copy
import hashlib
import json
import os
from pathlib import Path
import struct
import tempfile
import unittest
from unittest.mock import patch
from integratepbr_engine.atlas_source import parse_atlas_attribution,digest,strict_json
from integratepbr_engine.snapshot import validate_snapshot,prepare_snapshot,identity,LABELS,SCOPE
from integratepbr_engine.runtime_observation import parse_runtime_observation

FALSE_FLAGS=('source_metadata_verified','source_processing_equivalence_verified','load_time_provenance_verified','rendered_frame_verified','eligible_for_generation')

class AtlasSourceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        value=os.environ.get('INTEGRATEPBR_ATLAS_FIXTURE')
        if not value:raise AssertionError('INTEGRATEPBR_ATLAS_FIXTURE required: actual Java exporter')
        cls.root=Path(value)
    def packet(self,role):
        path=self.root/role;raw=(path/'observations/atlas-attribution.json').read_bytes();runtime_raw=(path/'observations/runtime.json').read_bytes();m=json.loads((path/'manifest.json').read_text(encoding='utf-8'));runtime=parse_runtime_observation(runtime_raw,m['selected_owner']);return raw,runtime_raw,runtime,path
    def parse(self,role,mutation=None,reader=None):
        raw,runtime_raw,runtime,path=self.packet(role)
        if mutation:
            value=json.loads(raw);mutation(value);raw=json.dumps(value,separators=(',',':')).encode()
        return parse_atlas_attribution(raw,runtime_raw,runtime,reader or (lambda name,count:(path/name).read_bytes()))
    def test_real_recipe_matches_and_no_source_retention(self):
        for role in ('direct','block_source','empty_source','hidden_rgb','directory','layers','missing_single','filter_readd','similar_pack','transform_override','metadata_unknown','safe_unknown','public_throw','public_nonempty','public_large','public_directory','manager_filtered_sidecar'):
            value=self.parse(role);self.assertEqual(value['origin'],'test_fixture');self.assertEqual(value['evidence_level'],'synthetic_atlas_correspondence')
            self.assertTrue(all(m['status']=='current_recipe_pixel_match' for m in value['mappings']),role)
            for key in FALSE_FLAGS:self.assertIs(value[key],False)
            self.assertEqual(value['adapter'],'blocks_current_recipe_v2')
            with tempfile.TemporaryDirectory() as temp:
                report=prepare_snapshot(self.root/role,Path(temp)/'prepare');self.assertEqual(report['jobs'],[]);self.assertEqual(report['atlas_attribution'],value)
                if role=='empty_source':self.assertTrue(report['atlas_attribution']['mappings']);self.assertEqual(report['coverage'],[])
        self.assertEqual(len(self.parse('layers')['atlases'][0]['definitions']),2)
        directory=self.parse('directory');r=directory['resources'][directory['mappings'][0]['actual_candidate']];self.assertEqual(r['resource_id'],'fixture:textures/folder/renamed.png');self.assertEqual(r['source_pack_id'],'effective-directory')
        trace=self.parse('filter_readd')['mappings'][0]['trace'];self.assertEqual([t['effect'] for t in trace],['add','remove','add'])
    def test_java_filter_transform_exclusion_and_unknown(self):
        expected={'filter_namespace':'missing_source','filter_default':'missing_source','generated_png':'generated_source_excluded','generated_definition':'generated_source_excluded','metadata':'unsupported_static_metadata','metadata_unknown':'current_recipe_pixel_match','dimension':'unsupported_static_metadata','apng':'unsupported_static_metadata','stale':'unknown_current_atlas','missing_identity':'unknown_current_atlas','unknown_atlas':'unknown_atlas','no_png':'missing_source','custom':'incomplete','malformed':'incomplete','budget':'incomplete','pixel_mismatch':'pixel_mismatch','public_pixel_mismatch':'pixel_mismatch','manager_same_sidecar':'unsupported_static_metadata','manager_higher_sidecar':'unsupported_static_metadata','manager_lower_sidecar':'unsupported_static_metadata','manager_filtered_png':'missing_source','source_present':'unsupported_static_metadata','sampler_metadata_false':'unsupported_static_metadata','sampler_metadata_null':'unsupported_static_metadata'}
        for role,status in expected.items():self.assertEqual(self.parse(role)['mappings'][0]['status'],status,role)
        for role in ('unstitch_exact','palette_exact'):
            maps=self.parse(role)['mappings'];self.assertEqual(maps[0]['status'],'transformed_source_unsupported');self.assertEqual(maps[1]['status'],'current_recipe_pixel_match')
        v=self.parse('generated_png');m=v['mappings'][0];actual=v['resources'][m['actual_candidate']];external=v['resources'][m['external_source_candidate']];self.assertEqual(actual['source_pack_id'],'file/IntegratePBR_Generated');self.assertIsNone(actual['source_path']);self.assertEqual(external['source_pack_id'],'fixture-png');self.assertIsNotNone(external['source_path'])
        v=self.parse('metadata');self.assertTrue(any(r['role']=='metadata' and r['source_pack_id']=='different-metadata-provider' for r in v['resources']))
    def test_independent_abgr_digest_and_hidden_rgb(self):
        self.assertEqual(digest(1,1,bytes([16,32,64,128])),hashlib.sha256(b'IPBR_RGBA8_V1\0'+struct.pack('>II',1,1)+bytes([16,32,64,128])).hexdigest())
        v=self.parse('direct');sample=v['mappings'][0]['sample'];pixels=bytes([16,32,64,0])+bytes([16,32,64,128])*54;self.assertEqual(sample['pixel_sha256'],digest(11,5,pixels))
        from PIL import Image
        r=v['resources'][v['mappings'][0]['actual_candidate']]
        with Image.open(self.root/'direct'/r['source_path']) as image:self.assertEqual(image.convert('RGBA').getpixel((0,0)),(16,32,64,0))
        mismatch=self.parse('pixel_mismatch');self.assertEqual(mismatch['mappings'][0]['status'],'pixel_mismatch')
    def test_corruption_preflight_and_identity(self):
        changes=[lambda v:v.update(extra=True),lambda v:v.update(runtime_sha256='0'*64),lambda v:v.update(origin='client_runtime_query'),lambda v:v.update(eligible_for_generation=True),lambda v:v['mappings'][0].update(sprite_handle=False),lambda v:v['mappings'][0].update(actual_candidate=0),lambda v:v['mappings'][0]['sample'].update(identity_before=1),lambda v:v['resources'][0].update(source_path='../escape'),lambda v:v['resources'][0].update(byte_count=True),lambda v:v['resources'][0].update(byte_count=262145),lambda v:v['resources'][0].update(generated_excluded=True),lambda v:v['mappings'][0]['trace'][0].update(source_index=99),lambda v:v['mappings'][0]['trace'][0].update(operation='directory'),lambda v:v['mappings'][0].update(winning_source_index=99),lambda v:v['mappings'][0].update(status='current_recipe_pixel_match')]
        for mutation in changes:
            with self.assertRaises(ValueError):self.parse('direct',mutation)
        self._preflight=self.packet('direct')
        with patch('pathlib.Path.read_bytes',side_effect=AssertionError('preflight must not open')):
            with self.assertRaises(ValueError):self.parse_raw_preflight()
        def corrupt(name,count):return b'bad'
        with self.assertRaises(ValueError):self.parse('direct',reader=corrupt)
        raw,rr,runtime,path=self.packet('direct')
        for malformed in (raw.replace(b'"schema_version":1',b'"schema_version":1,"schema_version":1',1),b'{"bad":"\\ud800"}',b'NaN',b'{"x":1e999}',b'['*40+b']'*40,b' '*8388609):
            with self.assertRaises(ValueError):strict_json(malformed)
    def parse_raw_preflight(self):
        # Cached input avoids a test-injected file open before the validator is entered.
        raw,runtime_raw,runtime,path=self._preflight
        v=json.loads(raw);v['resources'][0]['byte_count']=262145
        return parse_atlas_attribution(json.dumps(v).encode(),runtime_raw,runtime,lambda n,c:(_ for _ in ()).throw(AssertionError('opened')))
    def test_hash_transport_and_old_null_compatibility(self):
        self._preflight=self.packet('direct')
        with self.assertRaises(ValueError):self.parse_raw_preflight()
        for root in (Path(os.environ['INTEGRATEPBR_SNAPSHOT_FIXTURE']),Path(os.environ['INTEGRATEPBR_RUNTIME_FIXTURE'])/'item'):
            with tempfile.TemporaryDirectory() as temp:
                report=prepare_snapshot(root,Path(temp)/'prepare');self.assertIsNone(report['atlas_attribution']);self.assertEqual(len(validate_snapshot(root)),2)
        m=json.loads((self.root/'direct/manifest.json').read_text(encoding='utf-8'));changed=copy.deepcopy(m);changed['atlas_attribution']['sha256']='0'*64;self.assertNotEqual(identity(changed),m['snapshot_id'])
        with tempfile.TemporaryDirectory() as temp:
            import shutil
            target=Path(temp)/'copy';shutil.copytree(self.root/'direct',target);(target/'observations/atlas-attribution.json').write_bytes(b'{}')
            with self.assertRaises(ValueError):validate_snapshot(target)
    def test_declared_job_retains_atlas_without_forward(self):
        import torch
        from safetensors.torch import save_file
        from integratepbr_engine.network import ContextSwinUNet
        from integratepbr_engine.model_package import create_metadata
        with tempfile.TemporaryDirectory() as temp:
            work=Path(temp);torch.manual_seed(1234);labels=json.loads(LABELS.read_text(encoding='utf-8'));model=ContextSwinUNet(*(len(labels[k]) for k in ('materials','structures','objects','metals')));weights=work/'model.safetensors';save_file(model.state_dict(),str(weights));metadata=work/'model-metadata.json';metadata.write_text(json.dumps(create_metadata(weights,LABELS,sum(p.numel() for p in model.parameters()),package_id='random-atlas-fixture',version='fixture-1')),encoding='utf-8');m=json.loads((self.root/'direct/manifest.json').read_text(encoding='utf-8'));d=work/'declarations.json';d.write_text(json.dumps({'schema_version':1,'snapshot_id':m['snapshot_id'],'declarations':[{'resource_id':t['resource_id'],'source_sha256':t['source']['sha256'],'surface_kind':'item_surface','topology':'bounded_plane','orientation':'x_right_y_down','scope':SCOPE} for t in m['textures'] if t['source']]}),encoding='utf-8')
            with patch.object(ContextSwinUNet,'forward') as forward:report=prepare_snapshot(self.root/'direct',work/'prepared',metadata,d,experimental=True);forward.assert_not_called()
            self.assertEqual(len(report['jobs']),1);job=json.loads((work/'prepared'/report['jobs'][0]['job_path']).read_text(encoding='utf-8'));self.assertEqual(job['context']['evidence'][0]['value']['atlas_attribution'],report['atlas_attribution']);self.assertEqual(report['coverage'][1]['decision'],'conflict')

    def test_contract_bindings_final_identity_and_valid_apng(self):
        for role in ('pixel_stale','later_pixel_stale'):
            self.assertTrue(all(m['status']=='unknown_current_atlas' for m in self.parse(role)['mappings']))
        v=self.parse('safe_unknown');self.assertEqual(v['mappings'][0]['status'],'current_recipe_pixel_match');self.assertIsNotNone(v['mappings'][0]['sample']['pixel_sha256'])
        self.assertEqual(self.parse('structure_depth')['mappings'][0]['status'],'incomplete')
        for role,reason in [('source_budget','source_budget'),('transform_budget','transform_expansion_budget')]:
            v=self.parse(role);self.assertEqual(v['mappings'][0]['status'],'incomplete');self.assertTrue(any(o['code']==reason for o in v['omissions']))
        def change_actual(v):v['resources'][v['mappings'][0]['actual_candidate']]['resource_id']='fixture:textures/different_source.png'
        mutations=[change_actual,lambda v:v['mappings'][0]['trace'][0].update(effect='transformed'),lambda v:v['mappings'][0]['sample'].update(width=None,height=None),lambda v:v['atlases'][0].update(excluded_recipe=True),lambda v:v['resources'][v['mappings'][0]['external_source_candidate']].update(resource_id='other:textures/source.png')]
        for mutate in mutations:
            with self.assertRaises(ValueError):self.parse('direct',mutate)
        with self.assertRaises(ValueError):self.parse('directory',lambda v:v['resources'][v['mappings'][0]['actual_candidate']].update(resource_id='fixture:textures/folder/wrong.png'))
        raw,rr,runtime,path=self.packet('direct');v=json.loads(raw);v['mappings'][0]['sample'].update(width=2048,height=2048);calls=[]
        with self.assertRaises(ValueError):parse_atlas_attribution(json.dumps(v).encode(),rr,runtime,lambda p,c:calls.append(p))
        self.assertEqual(calls,[])
        v=self.parse('apng');asset=v['resources'][v['mappings'][0]['actual_candidate']];png=(self.root/'apng'/asset['source_path']).read_bytes();offset=8;chunks=[];controls={}
        import zlib,io
        while offset+12<=len(png):
            count=struct.unpack('>I',png[offset:offset+4])[0];kind=png[offset+4:offset+8];data=png[offset+8:offset+8+count];crc=struct.unpack('>I',png[offset+8+count:offset+12+count])[0];self.assertEqual(zlib.crc32(kind+data)&0xffffffff,crc);chunks.append(kind);
            if kind in (b'acTL',b'fcTL'):controls.setdefault(kind,[]).append(data)
            offset+=count+12
        self.assertIn(b'acTL',chunks);self.assertIn(b'fcTL',chunks)
        self.assertEqual(len(controls[b'acTL']),1);self.assertEqual(len(controls[b'fcTL']),1)
        self.assertEqual(struct.unpack('>II',controls[b'acTL'][0]),(1,0));self.assertEqual(struct.unpack('>III',controls[b'fcTL'][0][:12]),(0,11,5))
        self.assertLess(chunks.index(b'acTL'),chunks.index(b'IDAT'));self.assertLess(chunks.index(b'fcTL'),chunks.index(b'IDAT'))
        self.assertEqual(v['mappings'][0]['status'],'unsupported_static_metadata');self.assertIs(v['eligible_for_generation'],False)
        from PIL import Image
        # acTL identifies APNG; one declared frame has no Pillow animation playback flag.
        with Image.open(io.BytesIO(png)) as image:self.assertEqual(image.format,'PNG');self.assertEqual(image.size,(11,5));self.assertEqual(image.n_frames,1);self.assertFalse(image.is_animated);image.load()
        schema=json.loads((Path(__file__).resolve().parents[2]/'contracts/atlas-attribution.v1.schema.json').read_text(encoding='utf-8'));resource=schema['properties']['resources']['items'];self.assertEqual(resource['properties']['byte_count']['anyOf'][0]['maximum'],4194304);self.assertEqual(resource['allOf'][0]['then']['properties']['byte_count']['anyOf'][0]['maximum'],262144)

    def test_public_resource_and_manager_evidence(self):
        for role in ('public_throw','public_nonempty','public_large','public_directory','manager_filtered_sidecar'):
            raw,rr,runtime,path=self.packet(role);packet=json.loads(raw);value=self.parse(role);mapping=value['mappings'][0];actual=value['resources'][mapping['actual_candidate']]
            self.assertEqual(packet['adapter'],'blocks_current_recipe_v2');self.assertEqual(packet['origin'],'test_fixture')
            for key in FALSE_FLAGS[:2]:self.assertNotIn(key,packet)
            for key in FALSE_FLAGS:self.assertIs(value[key],False)
            self.assertEqual(mapping['status'],'current_recipe_pixel_match');self.assertEqual(actual['metadata_state'],'unknown');self.assertEqual(value['evidence_level'],'synthetic_atlas_correspondence')
            self.assertEqual(actual['source_pack_id'],'manager-low' if role=='manager_filtered_sidecar' else role)
            self.assertEqual(actual['resource_id'],'fixture:textures/folder/renamed.png' if role=='public_directory' else 'fixture:textures/source.png')
            self.assertFalse(any(r['role']=='metadata' for r in value['resources']))
            with tempfile.TemporaryDirectory() as temp:
                report=prepare_snapshot(path,Path(temp)/'prepared');self.assertEqual(report['jobs'],[]);self.assertEqual(report['atlas_attribution'],value)
        for role in ('manager_same_sidecar','manager_higher_sidecar','manager_lower_sidecar'):
            value=self.parse(role);mapping=value['mappings'][0];actual=value['resources'][mapping['actual_candidate']];sidecars=[r for r in value['resources'] if r['role']=='metadata']
            self.assertEqual(mapping['status'],'unsupported_static_metadata');self.assertEqual(len(sidecars),1);sidecar=sidecars[0]
            self.assertEqual(sidecar['resource_id'],'fixture:textures/source.png.mcmeta');self.assertEqual(sidecar['source_pack_id'],'manager-high' if role=='manager_higher_sidecar' else 'manager-low')
            self.assertEqual(actual['source_pack_id'],'manager-high' if role=='manager_lower_sidecar' else 'manager-low');self.assertEqual(actual['metadata_state'],'unknown')
            evidence=(self.root/role/sidecar['source_path']).read_bytes();self.assertEqual(json.loads(evidence),{'animation':{}});self.assertEqual(hashlib.sha256(evidence).hexdigest(),sidecar['sha256']);self.assertEqual(len(evidence),sidecar['byte_count'])
            for key in FALSE_FLAGS:self.assertIs(value[key],False)
        for role,expected in (('sampler_metadata_false',False),('sampler_metadata_null',None)):
            value=self.parse(role);self.assertIs(value['mappings'][0]['sample']['metadata_empty'],expected)
            for key in FALSE_FLAGS:self.assertIs(value[key],False)
        value=self.parse('source_present');self.assertEqual(value['resources'][value['mappings'][0]['actual_candidate']]['metadata_state'],'present')
        for key in FALSE_FLAGS:self.assertIs(value[key],False)
        for role in ('public_pixel_mismatch','manager_filtered_png'):
            value=self.parse(role)
            for key in FALSE_FLAGS:self.assertIs(value[key],False)

    def test_adapter_revision_compatibility(self):
        for role,adapter,status in (('direct','blocks_current_recipe_v1','current_recipe_pixel_match'),('metadata_unknown','blocks_current_recipe_v1','unsupported_static_metadata'),('metadata_unknown','blocks_current_recipe_v2','current_recipe_pixel_match')):
            raw,rr,runtime,path=self.packet(role);value=json.loads(raw);original=copy.deepcopy(value);value['adapter']=adapter
            if status=='unsupported_static_metadata':value['mappings'][0]['status']=status
            before=copy.deepcopy(value);report=parse_atlas_attribution(json.dumps(value).encode(),rr,runtime,lambda n,c:(path/n).read_bytes())
            self.assertEqual(report['mappings'][0]['status'],status);self.assertEqual(report['origin'],'test_fixture');self.assertEqual(report['evidence_level'],'synthetic_atlas_correspondence')
            for key in FALSE_FLAGS:self.assertIs(report[key],False)
            for key in FALSE_FLAGS[:2]:self.assertNotIn(key,value)
            if role=='metadata_unknown':self.assertEqual(report['resources'][report['mappings'][0]['actual_candidate']]['metadata_state'],'unknown')
            self.assertEqual(value,before);self.assertEqual(json.loads(raw),original);self.assertEqual((path/'observations/atlas-attribution.json').read_bytes(),raw)
        raw,rr,runtime,path=self.packet('metadata_unknown');unknown=json.loads(raw)
        direct_raw,direct_rr,direct_runtime,direct_path=self.packet('direct');direct=json.loads(direct_raw)
        cases=[]
        old=copy.deepcopy(unknown);old['adapter']='blocks_current_recipe_v1';cases.append((old,rr,runtime))
        present=copy.deepcopy(direct);present['resources'][present['mappings'][0]['actual_candidate']]['metadata_state']='present';cases.append((present,direct_rr,direct_runtime))
        unsupported=copy.deepcopy(direct);unsupported['adapter']='blocks_current_recipe_v3';cases.append((unsupported,direct_rr,direct_runtime))
        for key in FALSE_FLAGS[:2]:
            for flag in (False,True):
                injected=copy.deepcopy(direct);injected[key]=flag;cases.append((injected,direct_rr,direct_runtime))
        for key in FALSE_FLAGS[2:]:
            injected=copy.deepcopy(direct);injected[key]=True;cases.append((injected,direct_rr,direct_runtime))
        for value,runtime_raw,runtime_value in cases:
            calls=[]
            def forbidden_reader(name,count):calls.append(name);raise AssertionError('preflight opened evidence')
            with self.assertRaises(ValueError):parse_atlas_attribution(json.dumps(value).encode(),runtime_raw,runtime_value,forbidden_reader)
            self.assertEqual(calls,[])

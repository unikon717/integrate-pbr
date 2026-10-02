"""Detached current blocks-recipe validation and static pixel correspondence only."""
import hashlib
import io
import json
import math
import struct
from pathlib import Path
from PIL import Image
from .runtime_observation import _record,_int,_string,_id,_hash,_bool


def strict_json(raw,cap=8388608):
    if type(raw) is not bytes or len(raw)>cap:raise ValueError('atlas JSON byte bound')
    def pairs(items):
        result={}
        for key,value in items:
            if key in result:raise ValueError('duplicate atlas key')
            result[key]=value
        return result
    try:value=json.loads(raw.decode('utf-8'),object_pairs_hook=pairs,parse_constant=lambda x:(_ for _ in ()).throw(ValueError('nonfinite atlas JSON')))
    except (UnicodeError,json.JSONDecodeError,RecursionError) as exc:raise ValueError('invalid atlas JSON') from exc
    stack=[(value,0)];nodes=0
    while stack:
        v,d=stack.pop();nodes+=1
        if nodes>200000 or d>32:raise ValueError('atlas structure bound')
        if type(v) is str:
            try:v.encode('utf-8')
            except UnicodeError as exc:raise ValueError('atlas Unicode') from exc
        elif type(v) in (int,float):
            try:
                if not math.isfinite(v):raise ValueError('nonfinite atlas numeric')
            except OverflowError as exc:raise ValueError('overflow atlas numeric') from exc
        elif type(v) is list:stack.extend((x,d+1) for x in v)
        elif type(v) is dict:
            for k,x in v.items():stack.append((k,d+1));stack.append((x,d+1))
    return value


def digest(width,height,pixels):return hashlib.sha256(b'IPBR_RGBA8_V1\0'+struct.pack('>II',width,height)+pixels).hexdigest()


def _array(value,limit):
    if type(value) is not list or len(value)>limit:raise ValueError('atlas collection bound')


def _codes(value):
    _array(value,256)
    for code in value:_string(code)


def _ref(value,resources,role=None):
    _int(value,0,len(resources)-1);record=resources[value]
    if role is not None and record['role']!=role:raise ValueError('atlas reference role')
    return record


def _relative(value):
    _string(value)
    if not value.startswith('evidence/atlas/') or '\\' in value or ':' in value or any(p in ('','.','..') for p in value.split('/')):raise ValueError('atlas evidence path')


def _has_actl(raw):
    if raw[:8]!=b'\x89PNG\r\n\x1a\n':return True
    offset=8
    while offset+12<=len(raw):
        count=struct.unpack('>I',raw[offset:offset+4])[0];kind=raw[offset+4:offset+8]
        if kind==b'acTL':return True
        if count>len(raw)-offset-12:raise ValueError('invalid PNG chunks')
        offset+=count+12
        if kind==b'IEND':break
    return False


def parse_atlas_attribution(raw:bytes,runtime_raw:bytes,runtime:dict,read_evidence)->dict:
    value=strict_json(raw)
    _record(value,('schema_version','adapter','origin','selected_owner','runtime_sha256','load_time_provenance_verified','rendered_frame_verified','eligible_for_generation','pixel_digest_convention','atlases','resources','mappings','omissions'))
    if type(value['schema_version']) is not int or value['schema_version']!=1 or value['adapter'] not in ('blocks_current_recipe_v1','blocks_current_recipe_v2') or value['origin']!=runtime['origin'] or value['selected_owner']!=runtime['selected_owner'] or value['runtime_sha256']!=hashlib.sha256(runtime_raw).hexdigest():raise ValueError('atlas runtime identity')
    if any(value[k] is not False for k in ('load_time_provenance_verified','rendered_frame_verified','eligible_for_generation')) or value['pixel_digest_convention']!='ipbr_rgba8_dimensions_v1':raise ValueError('forbidden atlas proof')
    _array(value['atlases'],256);_array(value['resources'],1024);_array(value['mappings'],256);_array(value['omissions'],256)
    for o in value['omissions']:_record(o,('code','detail'));_string(o['code']);_string(o['detail'])
    inventory=value['resources'];paths=set();copied=0;definitions=0
    for index,r in enumerate(inventory):
        _record(r,('asset_id','role','resource_id','source_pack_id','layer','source_path','sha256','byte_count','generated_excluded','metadata_state'))
        if type(r['asset_id']) is not int or r['asset_id']!=index or r['role'] not in ('definition','png','metadata'):raise ValueError('atlas asset ordinal/role')
        _id(r['resource_id']);_string(r['source_pack_id']);_bool(r['generated_excluded'])
        if r['generated_excluded']!=(r['source_pack_id']=='file/IntegratePBR_Generated'):raise ValueError('excluded provider contradiction')
        if r['metadata_state'] not in ('not_applicable','empty','present','unknown'):raise ValueError('metadata state')
        if r['role']=='definition':
            _int(r['layer'],0,63)
            if r['resource_id']!='minecraft:atlases/blocks.json' or r['metadata_state']!='not_applicable':raise ValueError('definition role')
        elif r['layer'] is not None:raise ValueError('unexpected resource layer')
        if r['role']=='png' and (not r['resource_id'].split(':')[1].startswith('textures/') or not r['resource_id'].endswith('.png')):raise ValueError('PNG role path')
        if r['role']=='metadata' and (not r['resource_id'].endswith('.png.mcmeta') or r['metadata_state']!='not_applicable'):raise ValueError('metadata role path')
        fields=[r[k] is not None for k in ('source_path','sha256','byte_count')]
        if any(fields) and not all(fields):raise ValueError('partial captured asset identity')
        if all(fields):
            _relative(r['source_path']);_hash(r['sha256']);_int(r['byte_count'],0,4194304 if r['role']=='png' else 262144)
            if r['source_path'] in paths:raise ValueError('duplicate evidence path')
            paths.add(r['source_path']);copied+=r['byte_count']
            if r['role']=='definition':definitions+=r['byte_count']
            if r['generated_excluded'] and r['role']!='definition':raise ValueError('generated bytes forbidden')
        elif not r['generated_excluded']:raise ValueError('unexplained uncaptured resource')
    if copied>33554432 or definitions>4194304:raise ValueError('aggregate evidence budget')
    atlas_ids=set();definition_refs=set()
    for atlas in value['atlases']:
        _record(atlas,('atlas_id','info_id','status','excluded_recipe','definitions','reason_codes'));_id(atlas['atlas_id']);_bool(atlas['excluded_recipe']);_codes(atlas['reason_codes']);_array(atlas['definitions'],64)
        if atlas['atlas_id'] in atlas_ids or atlas['status'] not in ('complete','incomplete','unsupported'):raise ValueError('atlas duplicate/status')
        atlas_ids.add(atlas['atlas_id'])
        if atlas['atlas_id']=='minecraft:textures/atlas/blocks.png':
            if atlas['info_id']!='minecraft:blocks':raise ValueError('blocks info mapping')
        elif atlas['info_id'] is not None or atlas['definitions'] or atlas['status']!='unsupported':raise ValueError('invented atlas info')
        if atlas['excluded_recipe']!=any(_ref(d['asset_id'],inventory,'definition')['generated_excluded'] for d in atlas['definitions']):raise ValueError('atlas excluded recipe mismatch')
        for layer,d in enumerate(atlas['definitions']):
            _record(d,('layer','asset_id'));_int(d['layer'],0,63)
            if d['layer']!=layer:raise ValueError('definition layer order')
            r=_ref(d['asset_id'],inventory,'definition')
            if r['layer']!=layer or d['asset_id'] in definition_refs:raise ValueError('definition identity')
            definition_refs.add(d['asset_id'])
    sprites=runtime['sprites']
    if len(value['mappings'])!=len(sprites) or atlas_ids!={s['atlas_id'] for s in sprites}:raise ValueError('atlas observation coverage')
    total_trace=0;sample_pixels=0
    for index,m in enumerate(value['mappings']):
        _record(m,('sprite_handle','sprite_id','atlas_id','actual_candidate','external_source_candidate','winning_definition','winning_source_index','recipe_state','trace','sample','status','reason_codes'))
        if type(m['sprite_handle']) is not int or m['sprite_handle']!=index or m['sprite_id']!=sprites[index]['sprite_id'] or m['atlas_id']!=sprites[index]['atlas_id']:raise ValueError('sprite identity agreement')
        if m['recipe_state'] not in ('direct','transformed','absent','unknown') or m['status'] not in ('candidate','unknown_current_atlas','unknown_atlas','transformed_source_unsupported','generated_source_excluded','unsupported_static_metadata','incomplete','missing_source'):raise ValueError('atlas mapping enum')
        _codes(m['reason_codes']);_array(m['trace'],1024);total_trace+=len(m['trace'])
        for k in ('actual_candidate','external_source_candidate'):
            if m[k] is not None:_ref(m[k],inventory,'png')
        if m['external_source_candidate'] is not None and _ref(m['external_source_candidate'],inventory)['generated_excluded']:raise ValueError('external generated candidate')
        if (m['winning_definition'] is None)!=(m['winning_source_index'] is None):raise ValueError('partial winner')
        atlas=next(a for a in value['atlases'] if a['atlas_id']==m['atlas_id'])
        own_defs={d['asset_id'] for d in atlas['definitions']}
        if m['winning_definition'] is not None:
            _ref(m['winning_definition'],inventory,'definition');_int(m['winning_source_index'],0,2047)
            if m['winning_definition'] not in own_defs:raise ValueError('winner wrong atlas')
        if m['recipe_state']=='absent' and any(m[k] is not None for k in ('actual_candidate','external_source_candidate','winning_definition','winning_source_index')):raise ValueError('absent state has winner')
        if m['atlas_id']!='minecraft:textures/atlas/blocks.png' and (m['trace'] or m['recipe_state'] not in ('absent','unknown') or any(m[k] is not None for k in ('actual_candidate','external_source_candidate','winning_definition','winning_source_index'))):raise ValueError('invented unknown atlas recipe')
        if m['external_source_candidate'] is not None and (m['actual_candidate'] is None or inventory[m['external_source_candidate']]['resource_id']!=inventory[m['actual_candidate']]['resource_id']):raise ValueError('external resource differs from actual')
        for trace in m['trace']:
            _record(trace,('definition_asset_id','source_index','operation','effect'));_ref(trace['definition_asset_id'],inventory,'definition');_int(trace['source_index'],0,2047)
            if trace['definition_asset_id'] not in own_defs or trace['operation'] not in ('single','directory','filter','unstitch','paletted_permutations','unknown') or trace['effect'] not in ('add','replace','remove','missing','transformed','unknown'):raise ValueError('trace reference/enum')
            legal={'single':('add','replace','missing'),'directory':('add','replace','missing'),'filter':('remove',),'unstitch':('transformed','missing'),'paletted_permutations':('transformed','missing'),'unknown':('unknown',)}
            if trace['effect'] not in legal[trace['operation']]:raise ValueError('illegal trace effect')
        sample=m['sample'];_record(sample,('identity_before','identity_after','width','height','metadata_empty','pixel_sha256','reason_codes'));_codes(sample['reason_codes'])
        for k in ('identity_before','identity_after','metadata_empty'):
            if sample[k] is not None:_bool(sample[k])
        if (sample['width'] is None)!=(sample['height'] is None):raise ValueError('partial sample dimensions')
        if sample['width'] is not None:_int(sample['width'],1,2048);_int(sample['height'],1,2048)
        if sample['pixel_sha256'] is not None:
            _hash(sample['pixel_sha256'])
            if sample['width'] is None:raise ValueError('digest lacks dimensions')
            sample_pixels+=sample['width']*sample['height']
            if sample_pixels>4194304:raise ValueError('sample aggregate budget')
        atlas=next(a for a in value['atlases'] if a['atlas_id']==m['atlas_id'])
        if m['status']=='candidate':
            if value['omissions'] or atlas['reason_codes'] or m['reason_codes'] or sample['reason_codes'] or sample['width'] is None or (sample['width'],sample['height'])!=(sprites[index]['width'],sprites[index]['height']) or atlas['status']!='complete' or m['recipe_state']!='direct' or m['actual_candidate'] is None or m['winning_definition'] is None or sample['identity_before'] is not True or sample['identity_after'] is not True or sample['metadata_empty'] is not True or sample['pixel_sha256'] is None:raise ValueError('false candidate')
            actual=_ref(m['actual_candidate'],inventory,'png');winning=_ref(m['winning_definition'],inventory,'definition')
            if actual['generated_excluded'] or winning['generated_excluded'] or actual['source_path'] is None or actual['metadata_state'] not in (('empty',) if value['adapter']=='blocks_current_recipe_v1' else ('empty','unknown')):raise ValueError('excluded/nonstatic candidate')
    if total_trace>16384:raise ValueError('trace aggregate budget')
    # All inventory/links/budgets are validated before the first file open.
    files={}
    for r in inventory:
        if r['source_path'] is None:continue
        raw=read_evidence(r['source_path'],r['byte_count'])
        if type(raw) is not bytes or len(raw)!=r['byte_count'] or hashlib.sha256(raw).hexdigest()!=r['sha256']:raise ValueError('evidence bytes/hash mismatch')
        files[r['asset_id']]=raw
    docs={};source_total=0
    for asset in definition_refs:
        try:
            doc=strict_json(files[asset],262144)
            if type(doc) is not dict or set(doc)!= {'sources'} or type(doc['sources']) is not list:raise ValueError('captured definition shape')
            if source_total+len(doc['sources'])>2048:
                atlas=next(a for a in value['atlases'] if any(d['asset_id']==asset for d in a['definitions']))
                if atlas['status']!='incomplete' or not any(o['code']=='source_budget' for o in value['omissions']) or any(t['definition_asset_id']==asset for m in value['mappings'] for t in m['trace']) or any(m['status']=='candidate' for m in value['mappings'] if m['atlas_id']==atlas['atlas_id']):raise ValueError('unchecked source budget contradiction')
                docs[asset]=[];continue
            source_total+=len(doc['sources']);docs[asset]=doc['sources']
        except ValueError:
            atlas=next(a for a in value['atlases'] if any(d['asset_id']==asset for d in a['definitions']))
            if atlas['status']!='incomplete':raise
            docs[asset]=[]
    if source_total>2048:raise ValueError('definition source budget')
    for m in value['mappings']:
        ordered=[];last_winner=None
        for t in m['trace']:
            sources=docs[t['definition_asset_id']]
            if t['source_index']>=len(sources):raise ValueError('trace source bounds')
            source=sources[t['source_index']]
            if type(source) is not dict or type(source.get('type')) is not str:raise ValueError('trace source type')
            op=source['type'];op=op[10:] if op.startswith('minecraft:') else op
            expected=op if op in ('single','directory','filter','unstitch','paletted_permutations') else 'unknown'
            if t['operation']!=expected:raise ValueError('trace source operation mismatch')
            ordinal=(_ref(t['definition_asset_id'],inventory)['layer'],t['source_index']);ordered.append(ordinal)
            if t['effect'] in ('add','replace','transformed'):last_winner=(t['definition_asset_id'],t['source_index'])
            elif t['effect']=='remove':last_winner=None
        if ordered!=sorted(ordered):raise ValueError('trace order')
        if m['recipe_state'] in ('direct','transformed') and last_winner!=(m['winning_definition'],m['winning_source_index']):raise ValueError('winning trace identity')
        if m['recipe_state']=='direct':
            if m['actual_candidate'] is None or last_winner is None:raise ValueError('direct has no actual winner')
            source=docs[last_winner[0]][last_winner[1]];op=source['type'];op=op[10:] if op.startswith('minecraft:') else op
            actual=inventory[m['actual_candidate']]['resource_id']
            def rid(v):
                _string(v);v=v if ':' in v else 'minecraft:'+v;_id(v);return v
            if op=='single':
                if set(source)-{'type','resource','sprite'} or 'resource' not in source:raise ValueError('single declaration shape')
                resource=rid(source['resource']);target=rid(source.get('sprite',source['resource']));namespace,path=resource.split(':',1)
                if target!=m['sprite_id'] or actual!=namespace+':textures/'+path+'.png':raise ValueError('single actual candidate binding')
            elif op=='directory':
                if set(source)!= {'type','source','prefix'}:raise ValueError('directory declaration shape')
                for k in ('source','prefix'):
                    if type(source[k]) is not str or len(source[k].encode())>512 or '\\' in source[k] or ':' in source[k]:raise ValueError('unsafe directory declaration')
                    p=source[k].rstrip('/')
                    if p and any(segment in ('','.','..') for segment in p.split('/')):raise ValueError('unsafe directory prefix')
                namespace,path=actual.split(':',1);prefix='textures/'+source['source']+'/'
                if not path.startswith(prefix) or not path.endswith('.png') or namespace+':'+source['prefix']+path[len(prefix):-4]!=m['sprite_id']:raise ValueError('directory actual candidate binding')
            else:raise ValueError('non-direct winning source')
    result=json.loads(json.dumps(value));pixels_total=0
    for m in result['mappings']:
        if m['status']!='candidate':continue
        r=inventory[m['actual_candidate']];raw=files[m['actual_candidate']];sample=m['sample'];m['status']='pixel_mismatch'
        if _has_actl(raw):m['status']='unsupported_static_metadata';continue
        if any(x['role']=='metadata' and x['resource_id']==r['resource_id']+'.mcmeta' for x in inventory):raise ValueError('candidate metadata sidecar contradiction')
        try:
            with Image.open(io.BytesIO(raw)) as image:
                width,height=image.size
                if image.format!='PNG' or width>2048 or height>2048 or width<=0 or height<=0 or width*height>4194304:raise ValueError('PNG bounds')
                if getattr(image,'n_frames',1)!=1 or getattr(image,'is_animated',False):m['status']='unsupported_static_metadata';continue
                if (width,height)!=(sample['width'],sample['height']) or (width,height)!=(sprites[m['sprite_handle']]['width'],sprites[m['sprite_handle']]['height']):m['status']='unsupported_static_metadata';continue
                pixels_total+=width*height
                if pixels_total>4194304:raise ValueError('pixel aggregate bound')
                actual=digest(width,height,image.convert('RGBA').tobytes())
                if actual==sample['pixel_sha256']:m['status']='current_recipe_pixel_match'
        except (OSError,Image.DecompressionBombError) as exc:raise ValueError('invalid evidence PNG') from exc
    result['source_metadata_verified']=False
    result['source_processing_equivalence_verified']=False
    result['evidence_level']='synthetic_atlas_correspondence' if value['origin']=='test_fixture' else 'current_recipe_pixel_correspondence'
    return result

"""Pure strict detached query validation; neither origin is rendered-frame proof."""
import hashlib
import json
import math
import re
import struct


def _record(value,keys):
    if type(value) is not dict or set(value)!=set(keys):raise ValueError("invalid closed observation record")


def _int(value,minimum=None,maximum=None):
    if type(value) is not int or minimum is not None and value<minimum or maximum is not None and value>maximum:raise ValueError("invalid exact observation integer")
    return value


def _string(value,limit=512):
    if type(value) is not str or not value or len(value.encode("utf-8"))>limit:raise ValueError("invalid bounded string")


def _id(value):
    _string(value)
    if re.fullmatch(r"[a-z0-9_.-]+:[a-z0-9_./-]+",value) is None or any(part in ("",".","..") for part in value.split(":",1)[1].split("/")):raise ValueError("invalid namespaced ID")

def _typed_equal(a,b):
    if type(a) is not type(b):return False
    if type(a) is dict:return a.keys()==b.keys() and all(_typed_equal(a[k],b[k]) for k in a)
    if type(a) is list:return len(a)==len(b) and all(_typed_equal(x,y) for x,y in zip(a,b))
    return a==b

def _finite(value):
    if type(value) not in (int,float):raise ValueError("finite number required")
    try:
        if not math.isfinite(value):raise ValueError("nonfinite observation")
    except OverflowError as exc:raise ValueError("overflow observation") from exc
    return value


def _safe(value):
    stack=[(value,0)];count=0
    while stack:
        item,depth=stack.pop();count+=1
        if count>100000 or depth>32:raise ValueError("observation structure budget")
        if type(item) in (int,float):_finite(item)
        elif type(item) is str:item.encode("utf-8")
        elif type(item) is dict:
            for key,child in item.items():key.encode("utf-8");stack.append((child,depth+1))
        elif type(item) is list:stack.extend((child,depth+1) for child in item)


def _array(value,length):
    if type(value) is not list or len(value)!=length:raise ValueError("wrong numeric array")
    for item in value:_finite(item)


def _list(value,limit):
    if type(value) is not list or len(value)>limit:raise ValueError("observation collection bound")


def _bool(value):
    if type(value) is not bool:raise ValueError("boolean required")


def _hash(value):
    if type(value) is not str or re.fullmatch("[0-9a-f]{64}",value) is None:raise ValueError("invalid SHA256")


def _same(actual,expected):
    if not math.isclose(_finite(actual),expected,rel_tol=1e-9,abs_tol=1e-9):raise ValueError("packed derived value mismatch")


def parse_runtime_observation(raw:bytes,selected_owner:dict)->dict:
    if type(raw) is not bytes or len(raw)>4194304:raise ValueError("observation byte bound")
    def pairs(items):
        result={}
        for key,value in items:
            if key in result:raise ValueError("duplicate observation key")
            result[key]=value
        return result
    try:
        value=json.loads(raw.decode("utf-8"),object_pairs_hook=pairs,parse_constant=lambda x:(_ for _ in ()).throw(ValueError("nonfinite observation")))
        _safe(value)
    except (UnicodeError,json.JSONDecodeError,RecursionError) as exc:raise ValueError("invalid observation JSON") from exc
    _record(value,("schema_version","origin","adapter","selected_owner","status","context","models","queries","sprites","quads","limitations","omissions"))
    if type(value["schema_version"]) is not int or value["schema_version"]!=1 or value["adapter"]!="selected_baked_query_v1" or value["origin"] not in ("client_runtime_query","test_fixture") or value["selected_owner"]!=selected_owner:raise ValueError("observation identity mismatch")
    _record(selected_owner,("kind","id"));_id(selected_owner["id"])
    if selected_owner["kind"] not in ("item","block") or value["status"] not in ("complete","incomplete","unsupported"):raise ValueError("invalid status/owner")
    context=value["context"]
    _record(context,("selected_query_usage","dimension_id","game_time","rendered_frame_verified","visible_faces_evaluated","item","block"))
    if context["selected_query_usage"]!=selected_owner["kind"] or context["rendered_frame_verified"] is not False or context["visible_faces_evaluated"] is not False:raise ValueError("frame evidence forbidden")
    _id(context["dimension_id"]);_int(context["game_time"])
    item=selected_owner["kind"]=="item";arm=context["item" if item else "block"]
    if context["block" if item else "item"] is not None:raise ValueError("wrong context arm")
    if item:
        _record(arm,("stack_count","stack_encoding","stack_encoding_json","stack_encoding_sha256","context_identity_complete","entity_id","display_context","left_hand","model_seed","quad_seed","base_model_handle","resolved_model_handle","transformed_model_handle","pose_matrix","pose_scope"))
        _int(arm["stack_count"],1);_int(arm["entity_id"]);_int(arm["model_seed"]);_bool(arm["left_hand"]);_bool(arm["context_identity_complete"]);_string(arm["display_context"])
        if type(arm["quad_seed"]) is not int or arm["quad_seed"]!=42 or arm["pose_scope"]!="camera_transform_then_item_center":raise ValueError("invalid item query scope")
        if arm["stack_encoding"] is not None:
            if type(arm["stack_encoding"]) is not dict:raise ValueError("stack encoding object required")
            _hash(arm["stack_encoding_sha256"])
            _string(arm["stack_encoding_json"],65536)
            serialized=arm["stack_encoding_json"].encode("utf-8")
            if len(serialized)>65536 or hashlib.sha256(serialized).hexdigest()!=arm["stack_encoding_sha256"]:raise ValueError("stack encoding hash mismatch")
            try:encoded=json.loads(arm["stack_encoding_json"],object_pairs_hook=pairs,parse_constant=lambda x:(_ for _ in ()).throw(ValueError("nonfinite stack")))
            except (UnicodeError,json.JSONDecodeError,RecursionError) as exc:raise ValueError("invalid raw encoding") from exc
            _safe(encoded)
            if not _typed_equal(encoded,arm["stack_encoding"]) or not arm["context_identity_complete"]:raise ValueError("raw/parsed identity disagreement")
        elif arm["stack_encoding_sha256"] is not None or arm["stack_encoding_json"] is not None or arm["context_identity_complete"]:raise ValueError("missing stack identity")
        if arm["pose_matrix"] is not None:_array(arm["pose_matrix"],16)
        display=arm["display_context"]
        if display not in ("FIRST_PERSON_LEFT_HAND","FIRST_PERSON_RIGHT_HAND") or arm["left_hand"]!=(display=="FIRST_PERSON_LEFT_HAND") or arm["model_seed"]!=arm["entity_id"]+(3 if arm["left_hand"] else 4):raise ValueError("item display/seed mismatch")
        if value["status"]=="complete" and (arm["pose_matrix"] is None or not arm["context_identity_complete"]):raise ValueError("complete item context missing")
    else:
        _record(arm,("position","state_properties","render_shape","state_seed","model_handle","model_data_origin","input_model_data_empty","derived_model_data_empty","chunk_mesh_reproduction","block_entity_renderer_included"))
        if type(arm["position"]) is not list or len(arm["position"])!=3:raise ValueError("block position")
        for number in arm["position"]:_int(number)
        if type(arm["state_properties"]) is not dict or len(arm["state_properties"])>64:raise ValueError("state property bound")
        for key,child in arm["state_properties"].items():_string(key,256);_string(child,256)
        if arm["render_shape"] not in ("MODEL","INVISIBLE","ENTITYBLOCK_ANIMATED"):raise ValueError("invalid render shape")
        _int(arm["state_seed"])
        if arm["render_shape"]!="MODEL" and (value["status"]=="complete" or value["queries"]):raise ValueError("unsupported shape queried")
        if value["status"]=="complete" and any(arm[k] is None for k in ("model_handle","input_model_data_empty","derived_model_data_empty")):raise ValueError("complete block context missing")
        if arm["model_data_origin"]!="client_level_model_data_manager" or arm["chunk_mesh_reproduction"] is not False or arm["block_entity_renderer_included"] is not False:raise ValueError("block query scope")
        for key in ("input_model_data_empty","derived_model_data_empty"):
            if arm[key] is not None:_bool(arm[key])
    limits={"models":32,"queries":896,"sprites":256,"quads":2048,"limitations":256,"omissions":256}
    for key,limit in limits.items():_list(value[key],limit)
    for limitation in value["limitations"]:_string(limitation)
    for omission in value["omissions"]:_record(omission,("code","detail"));_string(omission["code"]);_string(omission["detail"])
    for index,model in enumerate(value["models"]):
        _record(model,("handle","class_name","resource_id"))
        if type(model["handle"]) is not int or model["handle"]!=index or model["resource_id"] is not None:raise ValueError("model handle identity")
        _string(model["class_name"])
    for key in (("base_model_handle","resolved_model_handle","transformed_model_handle") if item else ("model_handle",)):
        if arm[key] is not None:_int(arm[key],0,len(value["models"])-1)
        elif value["status"]=="complete":raise ValueError("complete model stage missing")
    for index,sprite in enumerate(value["sprites"]):
        _record(sprite,("sprite_handle","sprite_id","atlas_id","width","height","u0","u1","v0","v1","mapping_status"))
        if type(sprite["sprite_handle"]) is not int or sprite["sprite_handle"]!=index or sprite["mapping_status"]!="unknown":raise ValueError("sprite handle/mapping")
        _id(sprite["sprite_id"]);_id(sprite["atlas_id"]);_int(sprite["width"],1);_int(sprite["height"],1)
        for key in ("u0","u1","v0","v1"):
            if sprite[key] is not None:_finite(sprite[key])
    quadrefs=[]
    for index,query in enumerate(value["queries"]):
        _record(query,("query_id","model_handle","pass_index","render_type_index","render_type_class","render_type_diagnostic","bucket","seed","quad_indices","status","omission_codes"))
        if type(query["query_id"]) is not int or query["query_id"]!=index:raise ValueError("query ordinal")
        _int(query["model_handle"],0,len(value["models"])-1);_int(query["pass_index"],0,7);_int(query["render_type_index"],0,15);_int(query["seed"])
        if query["seed"]!=(42 if item else arm["state_seed"]) or query["bucket"] not in (None,"down","up","north","south","west","east") or query["status"] not in ("complete","incomplete","unsupported"):raise ValueError("invalid query semantics")
        for key in ("render_type_class","render_type_diagnostic"):
            if query[key] is not None:_string(query[key])
        _list(query["quad_indices"],128);_list(query["omission_codes"],256)
        for code in query["omission_codes"]:_string(code)
        for qid in query["quad_indices"]:_int(qid,0,len(value["quads"])-1);quadrefs.append((qid,index))
    if sorted(q for q,_ in quadrefs)!=list(range(len(value["quads"]))):raise ValueError("quad ownership references")
    for index,quad in enumerate(value["quads"]):
        _record(quad,("quad_id","query_id","tint_index","sprite_handle","facing","shade","ambient_occlusion","tint","packed_vertices","packed_vertex_count","decoded_vertices","local_sprite_uv","status","omission_codes"))
        _int(quad["query_id"],0,len(value["queries"])-1);_int(quad["tint_index"],-2147483648,2147483647)
        if type(quad["quad_id"]) is not int or quad["quad_id"]!=index or (index,quad["query_id"]) not in quadrefs:raise ValueError("quad ordinal/query")
        _bool(quad["shade"]);_bool(quad["ambient_occlusion"])
        if quad["facing"] not in ("down","up","north","south","west","east") or quad["status"] not in ("complete","incomplete","unsupported"):raise ValueError("quad status/facing")
        _list(quad["omission_codes"],256)
        for code in quad["omission_codes"]:_string(code)
        tint=quad["tint"];_record(tint,("status","raw_color","encoding","error_code"))
        if tint["status"] not in ("untinted","sampled","incomplete") or tint["encoding"]!=("item_argb32" if item else "block_color_int"):raise ValueError("tint context")
        if tint["raw_color"] is not None:_int(tint["raw_color"],-2147483648,2147483647)
        if tint["status"]=="sampled" and tint["raw_color"] is None or tint["status"]=="untinted" and tint["raw_color"] is not None:raise ValueError("tint status contradiction")
        if tint["error_code"] is not None:_string(tint["error_code"])
        if quad["tint_index"]==-1:
            if tint["status"]!="untinted" or tint["error_code"] is not None:raise ValueError("untinted index contradiction")
        elif tint["status"]=="untinted":raise ValueError("tinted index not sampled")
        if tint["status"]=="incomplete":
            if tint["raw_color"] is not None or tint["error_code"] is None or quad["status"]!="incomplete":raise ValueError("incomplete tint contradiction")
        elif tint["error_code"] is not None:raise ValueError("successful tint error")
        if quad["status"]=="complete" and quad["omission_codes"]:raise ValueError("complete quad omissions")
        count=_int(quad["packed_vertex_count"],0);packed=quad["packed_vertices"]
        if packed is not None:
            _list(packed,64)
            if len(packed)!=count:raise ValueError("packed count mismatch")
            for word in packed:_int(word,-2147483648,2147483647)
        elif count<=64:raise ValueError("unexpected missing packed array")
        sprite=None
        if quad["sprite_handle"] is not None:sprite=value["sprites"][_int(quad["sprite_handle"],0,len(value["sprites"])-1)]
        decoded=quad["decoded_vertices"];local=quad["local_sprite_uv"]
        if decoded is not None or local is not None:
            if count!=32 or packed is None or sprite is None or any(sprite[key] is None for key in ("u0","u1","v0","v1")) or sprite["u1"]<=sprite["u0"] or sprite["v1"]<=sprite["v0"]:raise ValueError("invalid decoded claim")
            _list(decoded,4);_list(local,4)
            if len(decoded)!=4 or len(local)!=4:raise ValueError("four decoded vertices required")
            for vertex in range(4):
                record=decoded[vertex];_record(record,("position","atlas_uv","vertex_color"));_array(record["position"],3);_array(record["atlas_uv"],2);_array(local[vertex],2)
                offset=vertex*8
                floats=[struct.unpack("!f",struct.pack("!I",packed[offset+j]&0xffffffff))[0] for j in (0,1,2,4,5)]
                if not all(math.isfinite(f) for f in floats):raise ValueError("nonfinite packed decoded claim")
                for actual,expected in zip(record["position"]+record["atlas_uv"],floats):_same(actual,expected)
                if record["vertex_color"]!=packed[offset+3] or type(record["vertex_color"]) is not int:raise ValueError("vertex color changed")
                for actual,expected in zip(local[vertex],((floats[3]-sprite["u0"])/(sprite["u1"]-sprite["u0"]),(floats[4]-sprite["v0"])/(sprite["v1"]-sprite["v0"]))):_same(actual,expected)
        elif quad["status"]=="complete":raise ValueError("complete quad lacks decoded values")
    for query in value["queries"]:
        if query["status"]=="complete" and (query["omission_codes"] or any(value["quads"][qid]["status"]!="complete" for qid in query["quad_indices"])):raise ValueError("complete query contradiction")
    if value["status"]!="incomplete" and (value["omissions"] or any(q["status"]=="incomplete" for q in value["queries"]+value["quads"])):raise ValueError("incomplete priority")
    if value["status"]=="complete" and (value["omissions"] or any(q["status"]!="complete" for q in value["queries"]+value["quads"])):raise ValueError("complete status contradiction")
    return {**value,"evidence_level":"live_baked_model_query" if value["origin"]=="client_runtime_query" else "synthetic_baked_model_query","selected_query_usage":context["selected_query_usage"],"rendered_frame_verified":False,"source_mapping":"unknown","sprite_groups":[{"sprite":sprite,"quad_ids":[q["quad_id"] for q in value["quads"] if q["sprite_handle"]==sprite["sprite_handle"]]} for sprite in value["sprites"]]}

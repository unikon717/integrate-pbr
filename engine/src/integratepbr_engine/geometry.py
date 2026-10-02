"""Pure bounded source-JSON geometry evidence; runtime rendering is never verified."""
import hashlib
import json
import math
import re

DIRECTIONS=("down","up","north","south","west","east")


def _id(value,prefix="",suffix=""):
    if type(value) is not str or not value: raise ValueError("invalid resource reference")
    namespaced=value if ":" in value else "minecraft:"+value
    if re.fullmatch(r"[a-z0-9_.-]+:[a-z0-9_./-]+",namespaced) is None: raise ValueError("invalid resource reference")
    namespace,path=namespaced.split(":")
    if namespace in (".","..") or any(p in ("",".","..") for p in path.split("/")): raise ValueError("unsafe reference")
    return namespace+":"+prefix+path+suffix


def _number(value):
    if type(value) not in (int,float):raise ValueError("finite number required")
    try:
        if not math.isfinite(value):raise ValueError("finite number required")
    except OverflowError as exc:raise ValueError("numeric value not representable") from exc
    return value


def _integer(value,minimum=None,choices=None):
    if type(value) is not int or minimum is not None and value<minimum or choices is not None and value not in choices: raise ValueError("invalid exact integer")
    return value


def _vector(value,length):
    if type(value) is not list or len(value)!=length: raise ValueError("invalid vector")
    return [_number(v) for v in value]


def _boolean(value):
    if type(value) is not bool: raise ValueError("boolean required")
    return value


def _parse(raw):
    def pairs(items):
        result={}
        for key,value in items:
            if key in result: raise ValueError("duplicate key")
            result[key]=value
        return result
    value=json.loads(raw.decode("utf-8"),object_pairs_hook=pairs,parse_constant=lambda v:(_ for _ in ()).throw(ValueError("nonfinite JSON")))
    stack=[(value,0)];nodes=0
    while stack:
        item,depth=stack.pop();nodes+=1
        if depth>64 or nodes>100000: raise ValueError("JSON parser budget")
        if type(item) in (float,int):_number(item)
        elif type(item) is str:item.encode("utf-8",errors="strict")
        elif type(item) is dict:
            for key,child in item.items():key.encode("utf-8",errors="strict");stack.append((child,depth+1))
        elif type(item) is list:stack.extend((child,depth+1) for child in item)
    if type(value) is not dict: raise ValueError("document must be object")
    return value


def default_uv(direction,start,end):
    fx,fy,fz=start;tx,ty,tz=end
    return {"down":[fx,16-tz,tx,16-fz],"up":[fx,fz,tx,tz],"north":[16-tx,16-ty,16-fx,16-fy],"south":[fx,16-ty,tx,16-fy],"west":[fz,16-ty,tz,16-fy],"east":[16-tz,16-ty,16-fz,16-fy]}[direction]


def resolve_geometry(manifest,documents:dict[str,bytes])->dict:
    if manifest["schema_version"]==1:return {"evidence_level":"geometry_evidence_unavailable","runtime_verified":False,"uses":[],"diagnostics":[]}
    inventory={d["resource_id"]:d for d in manifest["source_documents"]};parsed={};diagnostics=[];uses=[];face_count=0;element_count=0;effective_cache={}
    def provenance(rid):
        return {k:inventory[rid][k] for k in ("resource_id","source_pack_id","sha256")} if rid in inventory else {"resource_id":rid,"source_pack_id":None,"sha256":None}
    def document(rid):
        if rid in parsed:return parsed[rid]
        try:
            if rid not in documents:raise ValueError("missing source document")
            value=_parse(documents[rid]);parsed[rid]=(value,[])
        except (ValueError,UnicodeError,RecursionError) as exc:
            parsed[rid]=(None,["document_invalid:"+rid]);diagnostics.append({"document":provenance(rid),"reason":"source_document_invalid","detail":str(exc)})
        return parsed[rid]
    def effective(rid,active=()):
        if rid in active:return {"textures":{},"elements":[],"lineage":[],"family":"unresolved","incomplete":["parent_cycle"],"unsupported":[]}
        if len(active)>=64:return {"textures":{},"elements":[],"lineage":[],"family":"unresolved","incomplete":["parent_depth_limit"],"unsupported":[]}
        path=rid.split(":",1)[1]
        if path in ("models/builtin/generated.json","models/builtin/entity.json"):
            return {"textures":{},"elements":[],"lineage":[],"family":"generated_layers" if "generated" in path else "builtin_entity","incomplete":[],"unsupported":[]}
        if path.startswith("models/builtin/"):
            return {"textures":{},"elements":[],"lineage":[],"family":"unresolved","incomplete":[],"unsupported":["unknown_builtin"]}
        if rid in effective_cache:return effective_cache[rid]
        model,errors=document(rid)
        result={"textures":{},"elements":[],"lineage":[],"family":"vanilla_elements","incomplete":list(errors),"unsupported":[]}
        if model is None:return result
        result["lineage"]=[provenance(rid)]
        if "parent" in model:
            try:
                parent=effective(_id(model["parent"],"models/",".json"),active+(rid,))
                result={"textures":dict(parent["textures"]),"elements":list(parent["elements"]),"lineage":[provenance(rid)]+parent["lineage"],"family":parent["family"],"incomplete":list(parent["incomplete"]),"unsupported":list(parent["unsupported"])}
            except ValueError:result["incomplete"].append("invalid_parent")
        if "textures" in model:
            if type(model["textures"]) is not dict:result["incomplete"].append("invalid_textures")
            else:
                for key,value in model["textures"].items():
                    if type(value) is not str:result["incomplete"].append("invalid_texture_value")
                    else:result["textures"][key]=value
        if "elements" in model:
            if type(model["elements"]) is not list:result["incomplete"].append("invalid_elements")
            elif model["elements"]:result["elements"]=[(rid,i,e) for i,e in enumerate(model["elements"])]
        if any(key in model for key in ("loader","transform","visibility")):
            result["family"]="custom_geometry";result["unsupported"].extend("custom_"+key for key in ("loader","transform","visibility") if key in model)
        if "display" in model:result["unsupported"].append("display_transform_unbaked")
        if "render_type" in model:result["unsupported"].append("declared_render_type_hint")
        effective_cache[rid]=result
        return result
    def binding(raw,textures):
        if type(raw) is not str:raise ValueError("invalid face texture key")
        key=raw[1:] if raw.startswith("#") else raw
        seen=set()
        for _ in range(65):
            if key in seen:raise ValueError("texture_alias_cycle")
            seen.add(key)
            if key not in textures:raise ValueError("texture_alias_missing")
            value=textures[key]
            if value.startswith("#"):key=value[1:];continue
            return _id(value,"textures/",".png")
        raise ValueError("texture_alias_depth")
    def use(owner,root,model_id,branch,root_provenance):
        nonlocal face_count,element_count
        if len(uses)>=1024:
            if not any(d["reason"]=="use_budget" for d in diagnostics):diagnostics.append({"document":provenance(root),"reason":"use_budget","detail":"contextual use limit1024"})
            return
        facts=effective(model_id)
        item={"use_id":hashlib.sha256(json.dumps([owner,root,model_id,branch],sort_keys=True,ensure_ascii=False,allow_nan=False).encode()).hexdigest(),"owner":owner,"root_resource_id":root,"model_id":model_id,"branch":branch,"parent_lineage":facts["lineage"],"root_provenance":root_provenance,"family":facts["family"],"dependency_complete":False,"runtime_verified":False,"unsupported_reasons":list(facts["unsupported"]),"incomplete_reasons":list(facts["incomplete"]),"elements":[],"faces":[],"generated_layers":[]}
        if facts["family"]=="generated_layers":
            item["unsupported_reasons"].append("generated_side_geometry_unknown")
            for layer in range(5):
                key="layer"+str(layer)
                if key not in facts["textures"]:break
                try:item["generated_layers"].append({"layer":layer,"raw_texture":facts["textures"][key],"texture_resource_id":binding(key,facts["textures"]),"tintindex":layer,"runtime_tint":"unknown"})
                except ValueError as exc:item["incomplete_reasons"].append(str(exc))
        elif facts["family"]=="builtin_entity":item["unsupported_reasons"].append("builtin_entity_runtime_geometry")
        elif facts["family"]=="vanilla_elements":
            for source,index,element in facts["elements"]:
                if len(item["elements"])>=512 or element_count>=8192:
                    item["incomplete_reasons"].append("element_budget");break
                if len(item["faces"])>=512 or face_count>=8192:
                    item["incomplete_reasons"].append("face_budget");break
                try:
                    if type(element) is not dict:raise ValueError("invalid_element")
                    start=_vector(element.get("from"),3);end=_vector(element.get("to"),3)
                    shade=_boolean(element.get("shade",True))
                    if any(v< -16 or v>32 for v in start+end):item["unsupported_reasons"].append("coordinate_range_unsupported")
                    rotation=None
                    if "rotation" in element:
                        r=element["rotation"]
                        if type(r) is not dict or r.get("axis") not in ("x","y","z") or _number(r.get("angle")) not in (-45,-22.5,0,22.5,45):raise ValueError("invalid_element_rotation")
                        rotation={"origin":_vector(r.get("origin"),3),"axis":r["axis"],"angle":r["angle"],"rescale":_boolean(r.get("rescale",False))};item["unsupported_reasons"].append("element_rotation_unbaked")
                    faces=element.get("faces")
                    if type(faces) is not dict or not 1<=len(faces)<=6 or any(k not in DIRECTIONS for k in faces):raise ValueError("invalid_faces")
                    item["elements"].append({"source_document":provenance(source),"index":index,"from":start,"to":end,"shade":shade,"rotation":rotation,"coordinate_units":"model_0_to_16"})
                    element_count+=1
                    for direction,face in sorted(faces.items()):
                        if len(item["faces"])>=512 or face_count>=8192:
                            item["incomplete_reasons"].append("face_budget");break
                        try:
                            if type(face) is not dict:raise ValueError("invalid_face")
                            raw=face.get("texture");texture=binding(raw,facts["textures"])
                            uv=_vector(face["uv"],4) if "uv" in face else default_uv(direction,start,end)
                            angle=_integer(face.get("rotation",0),choices=(0,90,180,270))
                            cull=face.get("cullface")
                            if cull is not None and cull not in DIRECTIONS:raise ValueError("invalid_cullface")
                            tint=_integer(face.get("tintindex",-1),minimum=-1)
                            corners=[[uv[0],uv[1]],[uv[0],uv[3]],[uv[2],uv[3]],[uv[2],uv[1]]]
                            item["faces"].append({"source_document":provenance(source),"element_index":index,"direction":direction,"raw_texture":raw,"texture_resource_id":texture,"uv_origin":"explicit" if "uv" in face else "default","uv":uv,"rotation":angle,"uv_corners":[corners[(i+angle//90)%4] for i in range(4)],"cullface":cull,"tintindex":tint,"declared_face_tint":"none" if tint==-1 else "indexed","runtime_tint":"unknown","runtime_verified":False})
                            face_count+=1
                            if "neoforge_data" in face:item["unsupported_reasons"].append("neoforge_face_extension_unsupported")
                        except ValueError as exc:item["incomplete_reasons"].append(str(exc))
                except ValueError as exc:item["incomplete_reasons"].append(str(exc))
        if branch.get("x",0) or branch.get("y",0) or branch.get("uvlock",False):item["unsupported_reasons"].append("blockstate_transform_unbaked")
        item["incomplete_reasons"]=sorted(set(item["incomplete_reasons"]));item["unsupported_reasons"]=sorted(set(item["unsupported_reasons"]));item["dependency_complete"]=not item["incomplete_reasons"]
        uses.append(item)
    owners={json.dumps(o,sort_keys=True):o for t in manifest["textures"] for o in t["owners"]};owners[json.dumps(manifest["selected_owner"],sort_keys=True)]=manifest["selected_owner"]
    for owner in [owners[k] for k in sorted(owners)]:
        namespace,path=owner["id"].split(":")
        root=namespace+(":models/item/" if owner["kind"]=="item" else ":blockstates/")+path+".json"
        value,errors=document(root)
        if value is None:
            use(owner,root,root,{"kind":"unresolved_root"},provenance(root));continue
        if owner["kind"]=="item":
            use(owner,root,root,{"kind":"item_base"},provenance(root))
            overrides=value.get("overrides",[])
            if type(overrides) is not list:diagnostics.append({"document":provenance(root),"reason":"invalid_overrides","detail":"overrides must be array"});continue
            for index,override in enumerate(overrides):
                try:
                    if type(override) is not dict or type(override.get("predicate")) is not dict:raise ValueError("invalid override")
                    for key,number in override["predicate"].items():_id(key);_number(number)
                    use(owner,root,_id(override.get("model"),"models/",".json"),{"kind":"item_override","index":index,"predicate":override["predicate"],"raw_model":override["model"],"conditional":True,"selected":False},provenance(root))
                except ValueError as exc:diagnostics.append({"document":provenance(root),"reason":"invalid_override","detail":str(exc)})
        else:
            branches=[]
            variants=value.get("variants",{})
            if type(variants) is not dict:diagnostics.append({"document":provenance(root),"reason":"invalid_variants","detail":"variants must be object"})
            else:
                for selector,records in sorted(variants.items()):
                    if type(records) is list and not records:diagnostics.append({"document":provenance(root),"reason":"empty_variant_models","detail":"variant array is empty"})
                    for index,record in enumerate(records if type(records) is list else [records]):branches.append((record,{"kind":"variant","selector":selector,"index":index}))
            multipart=value.get("multipart",[])
            if type(multipart) is not list:diagnostics.append({"document":provenance(root),"reason":"invalid_multipart","detail":"multipart must be array"})
            else:
                for index,part in enumerate(multipart):
                    if type(part) is not dict or "apply" not in part:diagnostics.append({"document":provenance(root),"reason":"invalid_multipart","detail":"missing apply"});continue
                    if "when" in part and type(part["when"]) is not dict:
                        diagnostics.append({"document":provenance(root),"reason":"invalid_multipart_when","detail":"when must be object"});continue
                    if type(part["apply"]) is list and not part["apply"]:diagnostics.append({"document":provenance(root),"reason":"empty_multipart_apply","detail":"apply array is empty"})
                    for member,record in enumerate(part["apply"] if type(part["apply"]) is list else [part["apply"]]):branches.append((record,{"kind":"multipart","index":index,"member":member,"when":part.get("when"),"unconditional":"when" not in part}))
            for record,branch in branches:
                try:
                    if type(record) is not dict:raise ValueError("invalid model use")
                    branch.update(raw_model=record["model"],x=_integer(record.get("x",0),choices=(0,90,180,270)),y=_integer(record.get("y",0),choices=(0,90,180,270)),uvlock=_boolean(record.get("uvlock",False)),weight=_integer(record.get("weight",1),minimum=1))
                    use(owner,root,_id(record["model"],"models/",".json"),branch,provenance(root))
                except (ValueError,KeyError) as exc:diagnostics.append({"document":provenance(root),"reason":"invalid_model_use","detail":str(exc)})
    return {"evidence_level":"offline_json_geometry","runtime_verified":False,"uses":sorted(uses,key=lambda u:u["use_id"]),"diagnostics":sorted(diagnostics,key=lambda d:json.dumps(d,sort_keys=True))}

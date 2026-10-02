"""Immutable Java snapshot validation and explicit laboratory finite queue."""
import hashlib
import json
import math
import re
import shutil
import tempfile
from pathlib import Path
from PIL import Image
import numpy as np
from .pipeline import _validate_job, _write_json
from .model_package import ARCHITECTURE, sha256
from .preprocess import CURRENT_PREPROCESS_VERSION
from .usage import resolve_surface_usage
from .geometry import resolve_geometry
from .runtime_observation import parse_runtime_observation
from .atlas_source import parse_atlas_attribution

LABELS = Path(__file__).resolve().parents[3]/"contracts/labels.json"
SCOPE = "offline_image_plane_not_verified_game_uv"


def canonical(value):
    if value is None: return b"N"
    if type(value) is bool: return b"T" if value else b"F"
    if type(value) is int: return b"I"+str(value).encode()+b";"
    if type(value) is str:
        raw=value.encode("utf-8",errors="strict")
        return b"S"+str(len(raw)).encode()+b":"+raw
    if type(value) is list: return b"A"+str(len(value)).encode()+b":"+b"".join(canonical(v) for v in value)
    if type(value) is dict: return b"O"+str(len(value)).encode()+b":"+b"".join(canonical(k)+canonical(value[k]) for k in sorted(value))
    raise ValueError("canonical snapshot permits integers only")


def identity(manifest):
    return hashlib.sha256(canonical({k:v for k,v in manifest.items() if k!="snapshot_id"})).hexdigest()


def _pairs(pairs):
    result={}
    for key,value in pairs:
        if key in result: raise ValueError("duplicate JSON key")
        result[key]=value
    return result


def _read(path,limit=2097152):
    try:
        with Path(path).open("rb") as stream: raw=stream.read(limit+1)
        if len(raw)>limit: raise ValueError("JSON size bound")
        return json.loads(raw.decode("utf-8"),object_pairs_hook=_pairs,parse_constant=lambda value: (_ for _ in ()).throw(ValueError("nonfinite JSON")))
    except (UnicodeError,json.JSONDecodeError) as exc: raise ValueError("invalid UTF-8 JSON") from exc


def _record(value,keys):
    if type(value) is not dict or set(value)!=set(keys): raise ValueError("invalid closed snapshot record")


def _string(value):
    if type(value) is not str or not value: raise ValueError("nonempty string required")
    try: value.encode("utf-8")
    except UnicodeError as exc: raise ValueError("invalid Unicode scalar") from exc


def _int(value,minimum=0):
    if type(value) is not int or value<minimum: raise ValueError("invalid integer")


def _hash(value):
    if type(value) is not str or re.fullmatch("[0-9a-f]{64}",value) is None: raise ValueError("invalid digest")


def _id(value,texture=False):
    _string(value)
    if re.fullmatch(r"[a-z0-9_.-]+:[a-z0-9_./-]+",value) is None: raise ValueError("invalid resource ID")
    namespace,path=value.split(":")
    if namespace in (".","..") or any(p in ("",".","..") for p in path.split("/")): raise ValueError("unsafe resource ID")
    if texture and (not path.startswith("textures/") or not path.endswith(".png")): raise ValueError("invalid texture ID")


def _owner(value):
    _record(value,("kind","id"));_id(value["id"])
    if value["kind"] not in ("item","block"): raise ValueError("invalid owner kind")


def _ordered(values):
    if type(values) is not list: raise ValueError("array required")
    keys=[canonical(v) for v in values]
    if keys!=sorted(set(keys)): raise ValueError("unordered or duplicate records")


def _relative(value):
    _string(value)
    if any(c in value for c in ("\\",":")) or any(p in ("",".","..") for p in value.split("/")): raise ValueError("unsafe relative path")
    return Path(value)


def _validated(snapshot_root):
    root=Path(snapshot_root).resolve();manifest=_read(root/"manifest.json",8388608)
    if type(manifest) is not dict or type(manifest.get("schema_version")) is not int or manifest["schema_version"] not in (1,2,3,4): raise ValueError("unsupported snapshot schema")
    version=manifest["schema_version"]
    _record(manifest,("schema_version","snapshot_id","selected_owner","discovery","textures")+(("source_documents",) if version>=2 else ())+(("runtime_observation",) if version>=3 else ())+(("atlas_attribution",) if version==4 else ()))
    if version==1 and (root/"manifest.json").stat().st_size>2097152:raise ValueError("v1 manifest bound")
    documents={}
    if version>=2:
        inventory=manifest["source_documents"]
        if type(inventory) is not list or len(inventory)>8192:raise ValueError("document inventory bound")
        ids=[];paths=[];total=0
        for record in inventory:
            _record(record,("kind","resource_id","source_path","source_pack_id","sha256","byte_count"))
            rid=record["resource_id"];_id(rid);namespace,path=rid.split(":")
            if type(record["kind"]) is not str:raise ValueError("wrong document kind type")
            prefix={"model":"models/","blockstate":"blockstates/"}.get(record["kind"])
            if prefix is None or not path.startswith(prefix) or not path.endswith(".json"):raise ValueError("wrong document role")
            if record["source_path"]!="assets/"+namespace+"/"+path:raise ValueError("document path mismatch")
            _string(record["source_pack_id"]);_hash(record["sha256"]);_int(record["byte_count"])
            if record["byte_count"]>262144:raise ValueError("document byte bound")
            actual=(root/_relative(record["source_path"])).resolve()
            if not actual.is_relative_to(root) or actual==root:raise ValueError("document path escape")
            ids.append(rid);paths.append(record["source_path"]);total+=record["byte_count"]
        if ids!=sorted(set(ids)) or len(set(paths))!=len(paths) or total>8388608:raise ValueError("document duplicate/order/aggregate bound")
        for record in inventory:
            actual=(root/_relative(record["source_path"])).resolve()
            try:
                with actual.open("rb") as stream:raw=stream.read(record["byte_count"]+1)
            except FileNotFoundError as exc:raise ValueError("missing captured document") from exc
            if len(raw)!=record["byte_count"] or hashlib.sha256(raw).hexdigest()!=record["sha256"]:raise ValueError("document bytes/hash mismatch")
            documents[record["resource_id"]]=raw
    _hash(manifest["snapshot_id"]);_owner(manifest["selected_owner"])
    discovery=manifest["discovery"]
    _record(discovery,("scope","shared_scope_complete","owner_count","omissions"))
    if discovery["scope"]!="registry_json_candidates_v1" or type(discovery["shared_scope_complete"]) is not bool: raise ValueError("invalid discovery scope")
    _int(discovery["owner_count"])
    if discovery["owner_count"]>4096: raise ValueError("owner bound")
    _ordered(discovery["omissions"])
    for omission in discovery["omissions"]:
        _record(omission,("kind","owner","resource_id","detail"));_string(omission["kind"]);_string(omission["detail"])
        if omission["owner"] is not None: _owner(omission["owner"])
        if omission["resource_id"] is not None: _id(omission["resource_id"])
    if discovery["omissions"] and discovery["shared_scope_complete"]: raise ValueError("omissions cannot certify completeness")
    textures=manifest["textures"]
    if type(textures) is not list or len(textures)>128: raise ValueError("texture bound")
    ids=[];assets={};decoded={}
    def asset(value,expected):
        if value is None: return
        _record(value,("resource_id","source_path","source_pack_id","sha256","byte_count"));_id(value["resource_id"])
        if value["resource_id"]!=expected: raise ValueError("wrong asset role")
        _string(value["source_pack_id"]);_hash(value["sha256"]);_int(value["byte_count"])
        if value["byte_count"]>4194304: raise ValueError("asset size bound")
        namespace,path=expected.split(":")
        if value["source_path"]!="assets/"+namespace+"/"+path: raise ValueError("asset path mismatch")
        actual=(root/_relative(value["source_path"])).resolve()
        if not actual.is_relative_to(root) or actual==root: raise ValueError("asset escapes root")
        if actual.stat().st_size!=value["byte_count"] or sha256(actual)!=value["sha256"]: raise ValueError("asset bytes/hash mismatch")
        if value["source_path"] in assets and assets[value["source_path"]]!=value: raise ValueError("inconsistent duplicate asset")
        assets[value["source_path"]]=value
    for texture in textures:
        _record(texture,("resource_id","owners","evidence","source","width","height","sidecar","companions","context"))
        rid=texture["resource_id"];_id(rid,True);ids.append(rid)
        _ordered(texture["owners"])
        for owner in texture["owners"]: _owner(owner)
        if manifest["selected_owner"] not in texture["owners"]: raise ValueError("selected owner absent")
        _ordered(texture["evidence"])
        selected_evidence=False
        for evidence in texture["evidence"]:
            _record(evidence,("kind","owner","resource_id"));_owner(evidence["owner"]);_id(evidence["resource_id"])
            if evidence["kind"] not in ("model_texture_reference","armor_filename_candidate") or evidence["owner"] not in texture["owners"]: raise ValueError("invalid discovery evidence")
            selected_evidence |= evidence["owner"]==manifest["selected_owner"]
        if not selected_evidence: raise ValueError("selected owner evidence absent")
        _record(texture["companions"],("normal","specular"))
        asset(texture["source"],rid);asset(texture["sidecar"],rid+".mcmeta")
        asset(texture["companions"]["normal"],rid[:-4]+"_n.png");asset(texture["companions"]["specular"],rid[:-4]+"_s.png")
        context=texture["context"]
        _record(context,("renderer","render_surface","topology","orientation","tint","missing_fields"))
        for key in ("renderer","render_surface","topology","orientation","tint"):
            if context[key]!="unknown": raise ValueError("snapshot facts must remain unknown")
        if type(context["missing_fields"]) is not list or context["missing_fields"]!=sorted(set(context["missing_fields"])): raise ValueError("invalid missing context")
        for value in context["missing_fields"]: _string(value)
        if texture["source"] is None:
            if texture["width"] is not None or texture["height"] is not None: raise ValueError("absent source dimensions")
        else:
            for key in ("width","height"): _int(texture[key],1)
            w,h=texture["width"],texture["height"]
            if w>4096 or h>4096 or w*h>16777216: raise ValueError("pixel bound")
            with Image.open(root/texture["source"]["source_path"]) as image:
                if image.format!="PNG" or image.size!=(w,h): raise ValueError("PNG dimensions/format mismatch")
                decoded[rid]={"animated":getattr(image,"n_frames",1)>1 or getattr(image,"is_animated",False),"transparent":not np.any(np.asarray(image.convert("RGBA"))[:,:,3]>0)}
    if ids!=sorted(set(ids)): raise ValueError("unordered or duplicate texture IDs")
    if sum(a["byte_count"] for a in assets.values())>16777216: raise ValueError("aggregate asset bound")
    try: expected=identity(manifest)
    except UnicodeError as exc: raise ValueError("invalid Unicode") from exc
    if manifest["snapshot_id"]!=expected: raise ValueError("snapshot identity mismatch")
    observation=None
    if version>=3:
        descriptor=manifest["runtime_observation"]
        _record(descriptor,("observation_schema_version","source_path","sha256","byte_count"))
        if type(descriptor["observation_schema_version"]) is not int or descriptor["observation_schema_version"]!=1 or descriptor["source_path"]!="observations/runtime.json":raise ValueError("invalid observation descriptor")
        _hash(descriptor["sha256"]);_int(descriptor["byte_count"])
        if descriptor["byte_count"]>4194304:raise ValueError("observation byte bound")
        actual=(root/_relative(descriptor["source_path"])).resolve()
        if not actual.is_relative_to(root) or actual==root:raise ValueError("observation path escape")
        try:
            with actual.open("rb") as stream:raw=stream.read(descriptor["byte_count"]+1)
        except OSError as exc:raise ValueError("missing observation sidecar") from exc
        if len(raw)!=descriptor["byte_count"] or hashlib.sha256(raw).hexdigest()!=descriptor["sha256"]:raise ValueError("observation bytes/hash mismatch")
        observation=parse_runtime_observation(raw,manifest["selected_owner"])
    attribution=None
    if version==4:
        descriptor=manifest["atlas_attribution"]
        _record(descriptor,("attribution_schema_version","source_path","sha256","byte_count"))
        if type(descriptor["attribution_schema_version"]) is not int or descriptor["attribution_schema_version"]!=1 or descriptor["source_path"]!="observations/atlas-attribution.json":raise ValueError("invalid attribution descriptor")
        _hash(descriptor["sha256"]);_int(descriptor["byte_count"])
        if descriptor["byte_count"]>8388608:raise ValueError("attribution size bound")
        def bounded_file(path,count):
            actual=(root/_relative(path)).resolve()
            if not actual.is_relative_to(root) or actual==root:raise ValueError("attribution evidence escape")
            try:
                with actual.open("rb") as stream:data=stream.read(count+1)
            except OSError as exc:raise ValueError("missing attribution evidence") from exc
            if len(data)!=count:raise ValueError("attribution evidence count mismatch")
            return data
        data=bounded_file(descriptor["source_path"],descriptor["byte_count"])
        if hashlib.sha256(data).hexdigest()!=descriptor["sha256"]:raise ValueError("attribution sidecar hash")
        attribution=parse_atlas_attribution(data,raw,observation,bounded_file)
    return manifest,decoded,documents,observation,attribution


def validate_snapshot(snapshot_root):
    manifest,decoded,_,_,_=_validated(snapshot_root)
    return manifest,decoded


def _safe_metadata(value):
    if value is None or type(value) in (bool, int):
        return
    if type(value) is float:
        if not math.isfinite(value): raise ValueError("nonfinite metadata provenance")
        return
    if type(value) is str:
        try: value.encode("utf-8", errors="strict")
        except UnicodeError as exc: raise ValueError("invalid metadata Unicode") from exc
        return
    if type(value) is list:
        for child in value: _safe_metadata(child)
        return
    if type(value) is dict:
        for key,child in value.items(): _safe_metadata(key); _safe_metadata(child)
        return
    raise ValueError("invalid metadata JSON value")


def _package(path):
    if path is None: return None,False
    try:
        metadata=_read(path)
        _safe_metadata(metadata)
        if type(metadata) is not dict: return None,False
    except ValueError:
        return None,False
    try:
        if type(metadata) is not dict: raise ValueError("invalid metadata")
        for key,value in (("package_schema_version",1),("architecture",ARCHITECTURE),("preprocessing_version",CURRENT_PREPROCESS_VERSION),("weights_file","model.safetensors")):
            if type(metadata.get(key)) is not type(value) or metadata[key]!=value: raise ValueError("incompatible package")
        for key in ("package_id","version"): _string(metadata[key])
        for key in ("weights_sha256","labels_sha256"): _hash(metadata[key])
        _int(metadata["parameter_count"],1)
        if metadata["labels_sha256"]!=sha256(LABELS): raise ValueError("labels mismatch")
        return metadata,True
    except (ValueError,KeyError): return metadata,False


def prepare_snapshot(snapshot_root: Path, output_root: Path, package_metadata: Path|None=None, declarations: Path|None=None, *, experimental: bool=False) -> dict:
    manifest,decoded,documents,observation,attribution=_validated(snapshot_root)
    geometry=resolve_geometry(manifest,documents)
    root=Path(snapshot_root).resolve();output=Path(output_root).absolute()
    if output.exists() or output.is_symlink(): raise ValueError("prepared output exists")
    resolved=output.resolve()
    if resolved==root or resolved.is_relative_to(root) or root.is_relative_to(resolved) or any(p.lower()=="resourcepacks" for p in resolved.parts): raise ValueError("unsafe prepared output")
    for path in (package_metadata,declarations):
        if path is not None and (Path(path).resolve()==resolved or Path(path).resolve().is_relative_to(resolved)): raise ValueError("output contains input")
    if type(experimental) is not bool: raise ValueError("experimental flag must be boolean")
    declared={}
    records={t["resource_id"]:t for t in manifest["textures"]}
    if declarations is not None:
        if not experimental: raise ValueError("declarations require experimental opt-in")
        envelope=_read(declarations);_record(envelope,("schema_version","snapshot_id","declarations"))
        if type(envelope["schema_version"]) is not int or envelope["schema_version"]!=1 or envelope["snapshot_id"]!=manifest["snapshot_id"] or type(envelope["declarations"]) is not list: raise ValueError("stale or malformed declaration")
        for declaration in envelope["declarations"]:
            _record(declaration,("resource_id","source_sha256","surface_kind","topology","orientation","scope"))
            rid=declaration["resource_id"];_id(rid,True);_hash(declaration["source_sha256"])
            if rid not in records or rid in declared or records[rid]["source"] is None or declaration["source_sha256"]!=records[rid]["source"]["sha256"]: raise ValueError("unknown/duplicate/stale source declaration")
            if declaration["scope"]!=SCOPE or declaration["topology"]!="bounded_plane" or declaration["orientation"]!="x_right_y_down" or declaration["surface_kind"] not in ("item_surface","block_surface"): raise ValueError("unsupported declaration")
            kinds={o["kind"] for o in records[rid]["owners"]}
            if len(kinds)==1 and declaration["surface_kind"]!=next(iter(kinds))+"_surface": raise ValueError("declared surface disagrees with registry kind")
            declared[rid]=declaration
    package,compatible=_package(package_metadata)
    report={"schema_version":1,"snapshot_id":manifest["snapshot_id"],"experimental":experimental,"package":package,"jobs":[],"coverage":[],"geometry":geometry,"runtime_observation":observation,"atlas_attribution":attribution,"limitations":["registry JSON candidates only; shared discovery is not rendered-use completeness","offline image planes do not verify game renderer or UV","finite queue only; no automatic inference or active pack installation","model quality unverified"]}
    jobs=[]
    for texture in manifest["textures"]:
        rid=texture["resource_id"];kinds={o["kind"] for o in texture["owners"]}
        usage=resolve_surface_usage(resource_id=rid,evidence=[{"kind":"owner_use","value":o["kind"],"source":"registry_json_snapshot","verified":False,"owner":o["id"]} for o in texture["owners"]])
        reasons=["unknown_game_surface","unknown_game_uv_renderer"]
        blockers=[]
        if not manifest["discovery"]["shared_scope_complete"]: blockers.append("shared_scope_incomplete")
        if all(e["kind"]=="armor_filename_candidate" for e in texture["evidence"]): blockers.append("armor_candidate_unverified")
        if texture["source"] is None: blockers.append("missing_source")
        if texture["sidecar"] is not None or decoded.get(rid,{}).get("animated"): blockers.append("animation_unsupported")
        if any(a is not None for a in texture["companions"].values()): blockers.append("external_pbr_present")
        if decoded.get(rid,{}).get("transparent"): blockers.append("all_transparent")
        if len(kinds)>1: blockers.append("owner_use_conflict")
        if package_metadata is None: blockers.append("package_missing")
        elif not compatible: blockers.append("package_incompatible")
        geometry_uses=[u for u in geometry["uses"] if any(f.get("texture_resource_id")==rid for f in u["faces"]+u["generated_layers"])]
        if geometry["diagnostics"] or any(not u["dependency_complete"] for u in geometry["uses"]):blockers.append("geometry_incomplete")
        declaration=declared.get(rid)
        decision="conflict" if len(kinds)>1 else "skipped" if any(b not in ("package_missing","package_incompatible") for b in blockers) else "unresolved"
        if declaration is not None and not blockers:
            decision="prepared"
            namespace,path=rid.split(":");generation_id=namespace+":"+path[len("textures/"):-4]
            job_id=hashlib.sha256(canonical([manifest["snapshot_id"],rid])).hexdigest()
            source_path="inputs/"+namespace+"/"+path
            features=[0]*64;features[0]=int("block" in kinds);features[1]=int("item" in kinds);features[63]=1
            job={"protocol_version":1,"job_id":job_id,"resource_snapshot_id":manifest["snapshot_id"],"input":{"resource_id":generation_id,"source_path":source_path,"sha256":texture["source"]["sha256"],"width":texture["width"],"height":texture["height"]},"context":{"owners":sorted({o["id"] for o in texture["owners"]}),"evidence":[{"kind":"resource_snapshot","source":"registry_json_snapshot","value":{"snapshot_id":manifest["snapshot_id"],"discovery":manifest["discovery"],"texture":texture,"geometry":geometry,"runtime_observation":observation,"atlas_attribution":attribution,"associated_geometry_use_ids":[u["use_id"] for u in geometry_uses]}},{"kind":"offline_declaration","source":"explicit_experimental_opt_in","value":declaration}],"known_fields":["ownership","source"],"missing_fields":texture["context"]["missing_fields"],"attributes":{"surface_kind":declaration["surface_kind"],"topology":"bounded_plane","orientation":"x_right_y_down","metadata":features}},"policy":{"policy_id":"offline-generic-experimental","version":"1"},"model_package":{k:package[k] for k in ("package_id","version","architecture","preprocessing_version","weights_sha256","labels_sha256")},"output_dir":"outputs/"+job_id}
            _validate_job(job);jobs.append((job,texture))
            report["jobs"].append({"job_id":job_id,"resource_id":rid,"job_path":"jobs/"+job_id+".json"})
        report["coverage"].append({"resource_id":rid,"owners":texture["owners"],"discovery_evidence":texture["evidence"],"usage":usage,"owner_use_conflict":len(kinds)>1,"geometry_use_ids":[u["use_id"] for u in geometry_uses],"geometry_uses":geometry_uses,"decision":decision,"reasons":sorted(set(reasons+blockers)),"declaration":declaration})
    output.parent.mkdir(parents=True,exist_ok=True)
    if output.parent.resolve()!=output.parent: raise ValueError("symlink output parent")
    stage=Path(tempfile.mkdtemp(prefix=".integratepbr-prepared-",dir=output.parent))
    try:
        for job,texture in jobs:
            target=stage/job["input"]["source_path"];target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes((root/texture["source"]["source_path"]).read_bytes())
            if sha256(target)!=job["input"]["sha256"]: raise ValueError("prepared source changed")
            job_path=stage/"jobs"/(job["job_id"]+".json");job_path.parent.mkdir(exist_ok=True);_write_json(job_path,job)
        _write_json(stage/"report.json",report)
        if output.exists(): raise ValueError("prepared output appeared")
        stage.rename(output)
    finally:
        if stage.exists() and stage.parent.resolve()==output.parent.resolve() and stage.name.startswith(".integratepbr-prepared-"): shutil.rmtree(stage)
    return report

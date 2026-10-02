"""Local static experimental model compiler; every successful job remains partial."""
from __future__ import annotations
import json
import math
import re
import shutil
import tempfile
import time
from pathlib import Path
import numpy as np
from PIL import Image
import torch
import torch.nn.functional as F
from safetensors.torch import load_file
from .network import ContextSwinUNet, Prediction
from .preprocess import CURRENT_PREPROCESS_VERSION, preprocess_rgba
from .model_package import sha256, validate_package
from .constraints import validate_predictions, constrain_predictions
from .labpbr import encode_labpbr

METAL_CODES = dict(none=None, iron=230, gold=231, aluminum=232, chrome=233, copper=234, lead=235, platinum=236, silver=237, generic=255)
LIMITATIONS = ["uncalibrated semantics", "regional hierarchy and policies unsupported", "fine depth unapplied", "animation and UV transforms unsupported", "game and perceptual quality not evaluated", "deployment not evaluated"]


def _record(value, required, optional=()):
    if type(value) is not dict or not set(required) <= value.keys() or value.keys() - set(required) - set(optional):
        raise ValueError("missing or unknown record fields")


def _string(value):
    if type(value) is not str or not value:
        raise ValueError("expected nonempty string")


def _finite_json(value):
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError("nonfinite JSON")
    if isinstance(value, dict):
        for v in value.values(): _finite_json(v)
    if isinstance(value, list):
        for v in value: _finite_json(v)


def _relative(value):
    _string(value)
    if any(c in value for c in ("\\", ":")) or any(part in ("", ".", "..") for part in value.split("/")):
        raise ValueError("unsafe relative path")
    return Path(value)


def _child(root, value):
    path = (root / _relative(value)).resolve()
    if path == root or not path.is_relative_to(root):
        raise ValueError("path escapes job root")
    return path


def _hash(value):
    if type(value) is not str or re.fullmatch("[0-9a-f]{64}", value) is None:
        raise ValueError("invalid SHA-256")


def _validate_job(job):
    _record(job, ("protocol_version", "job_id", "resource_snapshot_id", "input", "context", "policy", "model_package", "output_dir"))
    if type(job["protocol_version"]) is not int or job["protocol_version"] != 1:
        raise ValueError("unsupported protocol")
    for key in ("job_id", "resource_snapshot_id"): _string(job[key])
    _finite_json(job)
    inp = job["input"]
    _record(inp, ("resource_id", "source_path", "sha256", "width", "height"), ("alpha_mode", "animation"))
    if type(inp["resource_id"]) is not str or re.fullmatch(r"[a-z0-9_.-]+:[a-z0-9_.-]+(?:/[a-z0-9_.-]+)*", inp["resource_id"]) is None:
        raise ValueError("unsafe resource ID")
    namespace, resource = inp["resource_id"].split(":")
    if resource.endswith(".png") or any(p in (".", "..") for p in resource.split("/")) or namespace in (".", ".."):
        raise ValueError("unsafe resource ID")
    _relative(inp["source_path"]); _relative(job["output_dir"]); _hash(inp["sha256"])
    for key in ("width", "height"):
        if type(inp[key]) is not int or inp[key] <= 0: raise ValueError("invalid dimensions")
    if "alpha_mode" in inp and inp["alpha_mode"] not in ("opaque", "cutout", "translucent", "unknown"):
        raise ValueError("invalid alpha mode")
    if "animation" in inp:
        animation = inp["animation"]
        _record(animation, ("frame_width", "frame_height", "frames", "interpolate"))
        for key in ("frame_width", "frame_height"):
            if type(animation[key]) is not int or animation[key] <= 0: raise ValueError("invalid frame size")
        if type(animation["interpolate"]) is not bool or type(animation["frames"]) is not list or not animation["frames"]: raise ValueError("invalid animation")
        for frame in animation["frames"]:
            _record(frame, ("index", "time"))
            if type(frame["index"]) is not int or frame["index"] < 0 or type(frame["time"]) is not int or frame["time"] <= 0: raise ValueError("invalid frame")
    context = job["context"]
    _record(context, ("owners", "evidence", "known_fields", "missing_fields", "attributes"))
    for key in ("owners", "known_fields", "missing_fields"):
        if type(context[key]) is not list: raise ValueError("invalid context list")
        for value in context[key]:
            _string(value)
            if key == "owners" and re.fullmatch(r"[a-z0-9_.-]+:[a-z0-9_./-]+", value) is None:
                raise ValueError("invalid namespaced owner ID")
        if key != "owners" and len(set(context[key])) != len(context[key]): raise ValueError("duplicate context fields")
    if type(context["evidence"]) is not list: raise ValueError("invalid evidence")
    for evidence in context["evidence"]:
        _record(evidence, ("kind", "source", "value")); _string(evidence["kind"]); _string(evidence["source"])
    attributes = context["attributes"]
    _record(attributes, ("surface_kind", "topology", "orientation"), ("metadata", "display_name"))
    for key in ("surface_kind", "topology", "orientation"): _string(attributes[key])
    if "display_name" in attributes and type(attributes["display_name"]) is not str: raise ValueError("invalid name")
    if "metadata" in attributes:
        values = attributes["metadata"]
        if type(values) is not list or len(values) != 64: raise ValueError("metadata must have 64 values")
        for i, value in enumerate(values):
            if type(value) not in (int, float) or not math.isfinite(value) or not 0 <= value <= 1 or (i < 32 or i >= 46) and value not in (0,1): raise ValueError("invalid metadata feature")
    policy = job["policy"]
    _record(policy, ("policy_id", "version"), ("overrides",))
    if policy["policy_id"] != "offline-generic-experimental" or type(policy["version"]) is not str or policy["version"] != "1": raise ValueError("unsupported policy")
    overrides = policy.get("overrides", {})
    _record(overrides, (), ("max_depth_alpha",))
    cap = overrides.get("max_depth_alpha", 2.0)
    if type(cap) not in (int,float) or not math.isfinite(cap) or not 0 <= cap <= 2: raise ValueError("invalid depth cap")
    package = job["model_package"]
    _record(package, ("package_id", "version", "architecture", "preprocessing_version", "weights_sha256", "labels_sha256"))
    for key in ("package_id", "version", "architecture", "preprocessing_version"): _string(package[key])
    for key in ("weights_sha256", "labels_sha256"): _hash(package[key])
    return cap


def _labels(path):
    labels = json.loads(path.read_text(encoding="utf-8"))
    for key in ("materials", "structures", "objects", "metals"):
        values = labels.get(key)
        if type(values) is not list or not values or any(type(v) is not str or not v for v in values) or len(set(values)) != len(values): raise ValueError("invalid vocabulary")
    if "metal" not in labels["materials"] or "unknown" not in labels["objects"] or "unknown" not in labels["materials"] or "unknown" not in labels["structures"] or labels["metals"][0] != "none" or set(labels["metals"]) != set(METAL_CODES): raise ValueError("missing vocabulary names")
    mapping = labels.get("metal_labpbr_green")
    if type(mapping) is not dict or mapping != METAL_CODES or any(type(mapping[k]) is not int for k in mapping if k != "none"): raise ValueError("invalid metal byte mapping")
    return labels


def _write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")


def _check_artifacts(stage, albedo, source_bytes, rgba, normal, specular, constrained):
    normal_path = albedo.with_name(albedo.stem+"_n.png")
    specular_path = albedo.with_name(albedo.stem+"_s.png")
    if set(stage.glob("assets/*/textures/**/*.png")) != {albedo, normal_path, specular_path}:
        raise ValueError("wrong image inventory")
    for path, expected in ((albedo, rgba), (normal_path, normal), (specular_path, specular)):
        with Image.open(path) as image:
            decoded = np.asarray(image.convert("RGBA"))
        if decoded.shape != rgba.shape or not np.array_equal(decoded, expected):
            raise ValueError("artifact dimensions or pixels changed")
    if albedo.read_bytes() != source_bytes:
        raise ValueError("source PNG bytes changed")
    invalid = ~constrained["valid"]
    if not np.all(normal[invalid] == (128,128,255,255)) or not np.all(specular[invalid] == 0): raise ValueError("transparent neutrality failed")
    if not np.all(np.isin(specular[:,:,1], list(range(230))+list(v for v in METAL_CODES.values() if v is not None))): raise ValueError("invalid specular code")


def generate_job(job_path: Path, job_root: Path, weights: Path, labels_path: Path) -> dict:
    start = time.perf_counter()
    job = json.loads(Path(job_path).read_text(encoding="utf-8"))
    # Only trustworthy envelope identity can be echoed in a result.
    if type(job) is not dict or type(job.get("protocol_version")) is not int or job.get("protocol_version") != 1: raise ValueError("invalid job envelope")
    for key in ("job_id", "resource_snapshot_id"): _string(job.get(key))
    result = {"protocol_version":1, "job_id":job["job_id"], "resource_snapshot_id":job["resource_snapshot_id"], "status":"failed", "engine_version":"0.1.0", "model_version":"unverified", "preprocessing_version":CURRENT_PREPROCESS_VERSION, "files":[], "checks":[], "fallback":{"used":False,"reason":None}, "timing":{"total_ms":0,"stages_ms":{}}}
    stage = None
    code = "JOB_INVALID"
    def finish():
        result["timing"]["total_ms"] = (time.perf_counter()-start)*1000
        return result
    def skip(reason):
        result["status"] = "skipped"
        result["checks"].append({"name":"supported_profile", "passed":False,"detail":reason})
        return finish()
    try:
        cap = _validate_job(job)
        root = Path(job_root).resolve()
        source, output = _child(root,job["input"]["source_path"]), _child(root,job["output_dir"])
        code = "INPUT_INVALID"
        if output.exists() or output.is_symlink(): raise ValueError("output already exists")
        for protected in (source, Path(weights).resolve(), Path(labels_path).resolve()):
            if protected == output or protected.is_relative_to(output): raise ValueError("output encompasses protected input")
        if source.suffix.lower() != ".png" or sha256(source) != job["input"]["sha256"]: raise ValueError("source PNG hash mismatch")
        source_bytes = source.read_bytes()
        with Image.open(source) as image:
            if image.format != "PNG": raise ValueError("source is not PNG")
            embedded_animation = getattr(image, "n_frames", 1) > 1 or getattr(image, "is_animated", False)
            rgba = np.asarray(image.convert("RGBA")).copy()
        h,w = rgba.shape[:2]
        if (w,h) != (job["input"]["width"],job["input"]["height"]): raise ValueError("source dimensions mismatch")
        if embedded_animation: return skip("embedded PNG animation unsupported")
        alpha = rgba[:,:,3]
        mode = job["input"].get("alpha_mode")
        if mode == "opaque" and not np.all(alpha == 255) or mode == "cutout" and not np.all((alpha == 0)|(alpha == 255)): raise ValueError("alpha declaration mismatch")
        attributes = job["context"]["attributes"]
        if "animation" in job["input"] or source.with_name(source.name+".mcmeta").exists(): return skip("animation metadata unsupported")
        if attributes["surface_kind"] not in ("item_surface","block_surface") or attributes["topology"] != "bounded_plane" or attributes["orientation"] != "x_right_y_down": return skip("surface/topology/orientation unsupported")
        if not np.any(alpha > 0): return skip("all-transparent source")
        code = "PACKAGE_INVALID"
        labels = _labels(Path(labels_path))
        metadata = validate_package(Path(weights),Path(labels_path))
        for key,value in job["model_package"].items():
            if type(metadata.get(key)) is not str or metadata[key] != value: raise ValueError(f"package identity mismatch: {key}")
        model = ContextSwinUNet(len(labels["materials"]),len(labels["structures"]),len(labels["objects"]),len(labels["metals"]))
        if metadata["parameter_count"] != sum(p.numel() for p in model.parameters()): raise ValueError("parameter count mismatch")
        model.load_state_dict(load_file(str(weights),device="cpu"),strict=True)
        model.cpu().eval()
        result["model_version"] = metadata["version"]
        features = attributes.get("metadata", [0.0]*63+[1.0])
        name = list(attributes.get("display_name", "").encode("utf-8")[:96])
        image = torch.from_numpy(preprocess_rgba(rgba,version=CURRENT_PREPROCESS_VERSION).transpose(2,0,1)).unsqueeze(0)
        image = F.pad(image,(0,(-w)%8,0,(-h)%8))
        code = "PREDICTION_INVALID"
        with torch.inference_mode():
            prediction = model(image,torch.tensor([features],dtype=torch.float32),torch.tensor([name or [0]],dtype=torch.long))
        validate_predictions(prediction,labels,*image.shape[-2:])
        prediction = Prediction(*(value if value.ndim == 2 else value[:,:,:h,:w] for value in prediction))
        constrained = constrain_predictions(prediction,alpha>0,labels,max_depth_alpha=cap)
        normal,specular = encode_labpbr(constrained,labels)
        if np.any(constrained["depth_byte"] > cap): raise ValueError("depth bound failed")
        code = "OUTPUT_FAILED"
        output.parent.mkdir(parents=True,exist_ok=True)
        stage = Path(tempfile.mkdtemp(prefix=".integratepbr-stage-",dir=output.parent)).resolve()
        if not stage.is_relative_to(root): raise ValueError("staging escapes root")
        namespace,resource = job["input"]["resource_id"].split(":")
        albedo = stage / "assets" / namespace / "textures" / (resource+".png")
        albedo.parent.mkdir(parents=True,exist_ok=True)
        albedo.write_bytes(source_bytes)
        Image.fromarray(normal).save(albedo.with_name(albedo.stem+"_n.png"))
        Image.fromarray(specular).save(albedo.with_name(albedo.stem+"_s.png"))
        raw = {name:(value[0,0] if value.ndim==4 and value.shape[1]==1 else value[0]).detach().cpu().numpy().astype(np.float32) for name,value in zip(prediction._fields,prediction)}
        np.savez(stage / "predictions.npz",**raw)
        provenance = {"job":job,"job_sha256":sha256(Path(job_path)),"source_sha256":sha256(source),"package":metadata,"package_metadata_sha256":sha256(Path(weights).resolve().parent/"model-metadata.json"),"policy_sha256":__import__("hashlib").sha256(json.dumps(job["policy"],sort_keys=True,allow_nan=False).encode()).hexdigest(),"code_sha256":{p.name:sha256(p) for p in (Path(__file__),Path(__file__).with_name("constraints.py"),Path(__file__).with_name("labpbr.py"),Path(__file__).with_name("network.py"),Path(__file__).with_name("preprocess.py"),Path(__file__).with_name("model_package.py"))},"metadata":features,"metadata_defaulted":"metadata" not in attributes,"name_utf8_bytes":name,"name_padded_bytes":name or [0],"native_dimensions":[w,h],"padded_dimensions":[image.shape[-1],image.shape[-2]],"declarations_are_unverified":True,"unused_context_evidence":job["context"],"quality_status":metadata.get("quality_status","unverified"),"fine_depth_applied":False,"max_depth_alpha":cap,"depth_rounding":"floor","metal_thresholds":0.5,"normal_scale":0.25,"du":1/w,"dv":1/h,"alpha_coverage":{"nonempty":int((alpha>0).sum()),"partial":int(((alpha>0)&(alpha<255)).sum())},"limitations":LIMITATIONS}
        _write_json(stage/"provenance.json",provenance)
        _check_artifacts(stage,albedo,source_bytes,rgba,normal,specular,constrained)
        result["status"] = "partial"
        result["checks"] = [{"name":name,"passed":True} for name in ("cpu_forward", "source_png_and_rgba_preserved", "dimensions", "numeric_bounds", "discrete_metal_codes", "transparent_neutrality", "output_hashes")]+[{"name":"experimental_limitations","passed":False,"detail":"; ".join(LIMITATIONS)}]
        for path in sorted(stage.rglob("*")):
            if path.is_file(): result["files"].append({"path":path.relative_to(stage).as_posix(),"sha256":sha256(path),"bytes":path.stat().st_size,"role":"albedo" if path==albedo else path.stem})
        finish()
        _write_json(stage/"result.json",result)
        for entry in result["files"]:
            if sha256(stage/entry["path"]) != entry["sha256"]: raise ValueError("inventory hash mismatch")
        if output.exists(): raise ValueError("output appeared during execution")
        stage.rename(output)
        stage = None
        return result
    except Exception as exc:
        result["status"] = "failed"; result["files"] = []
        result["error"] = {"code":code,"message":str(exc)}
        result["checks"].append({"name":"execution","passed":False,"detail":str(exc)})
        return finish()
    finally:
        if stage is not None and stage.exists() and stage.is_relative_to(root) and stage.name.startswith(".integratepbr-stage-"):
            shutil.rmtree(stage)

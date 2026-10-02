"""Deterministic bounded-plane DirectX LabPBR encoding."""
import math
import numpy as np


def height_to_normal_xy(height, valid, *, du, dv):
    height = np.asarray(height)
    valid = np.asarray(valid, dtype=bool)
    if height.ndim != 2 or height.shape != valid.shape or not np.isfinite(height).all() or not all(math.isfinite(x) and x > 0 for x in (du, dv)):
        raise ValueError("invalid height or spacing")
    z = height.astype(np.float64) * (0.25 / 255)
    neighbors = []
    for axis, shift in ((1, 1), (1, -1), (0, 1), (0, -1)):
        other = np.roll(z, shift, axis=axis)
        mask = np.roll(valid, shift, axis=axis)
        edge = [slice(None), slice(None)]
        edge[axis] = 0 if shift == 1 else -1
        mask[tuple(edge)] = False
        neighbors.append(np.where(mask, other, z))
    left, right, up, down = neighbors
    x, y = -(right-left)/(2*du), -(down-up)/(2*dv)
    scale = np.sqrt(x*x+y*y+1)
    xy = np.stack((x/scale, y/scale), axis=-1)
    xy[~valid] = 0
    return xy


def _byte(value):
    return np.floor(np.clip(value, 0, 255) + 0.5).astype(np.uint8)


def encode_labpbr(constrained, labels):
    valid, height = constrained["valid"], constrained["height"]
    h, w = valid.shape
    xy = height_to_normal_xy(height, valid, du=1/w, dv=1/h)
    normal = np.empty((h,w,4), dtype=np.uint8)
    normal[:,:,:2] = _byte(255*(xy*0.5+0.5))
    normal[:,:,2] = _byte(255*constrained["ao"])
    normal[:,:,3] = height
    specular = np.zeros_like(normal)
    specular[:,:,0] = _byte(255*constrained["smoothness"])
    specular[:,:,1] = np.minimum(_byte(255*constrained["dielectric_f0"]),229)
    for index, name in enumerate(labels["metals"]):
        if name != "none":
            specular[:,:,1][constrained["metal_indices"] == index] = labels["metal_labpbr_green"][name]
    normal[~valid] = (128,128,255,255)
    specular[~valid] = 0
    return normal, specular

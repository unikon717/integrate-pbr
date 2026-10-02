"""Compact context-conditioned Swin U-Net prototype for pixel-art PBR.

The stem and high-resolution skip paths preserve single source texels. Window
attention adds texture-wide context at multiple scales. This is an untrained
architecture prototype; it does not promise generation quality.
"""

from __future__ import annotations

from typing import NamedTuple

try:
    import torch
    from torch import Tensor, nn
    import torch.nn.functional as F
except ImportError as exc:  # The Java resource-pack manager has no ML dependency.
    raise RuntimeError("The model prototype requires the optional 'train' dependencies") from exc


class Prediction(NamedTuple):
    object_type: Tensor
    object_materials: Tensor
    material: Tensor
    structure: Tensor
    boundary: Tensor
    base_depth: Tensor
    fine_depth: Tensor
    smoothness: Tensor
    dielectric_f0: Tensor
    metal_type: Tensor
    ao: Tensor


def constrained_metal_probabilities(prediction: Prediction, *,
                                    metal_material_index: int = 3,
                                    unknown_object_type_index: int = 0,
                                    threshold: float = 0.5) -> Tensor:
    """Require a recognized object type, metal composition and local metal region.

    The no-metal channel is index zero. A wooden tool can still be a tool, but its
    metal reflection stays disabled unless the type is recognized, composition
    includes metal, and both dense classifiers identify the pixel as metal.
    """
    pixel_material = prediction.material.softmax(dim=1)[:, metal_material_index]
    object_material = prediction.object_materials.sigmoid()[:, metal_material_index]
    object_type_scores = prediction.object_type.softmax(dim=1)
    recognized_type = ((object_type_scores.argmax(dim=1) != unknown_object_type_index) &
                       (object_type_scores.amax(dim=1) >= threshold))
    allowed = (recognized_type[:, None, None] &
               (object_material >= threshold)[:, None, None] &
               (pixel_material >= threshold))
    probabilities = prediction.metal_type.softmax(dim=1)
    metal = probabilities[:, 1:] * allowed[:, None].to(probabilities.dtype)
    no_metal = (1.0 - metal.sum(dim=1, keepdim=True)).clamp(0.0, 1.0)
    return torch.cat((no_metal, metal), dim=1)


class ConvNormAct(nn.Sequential):
    def __init__(self, in_channels: int, out_channels: int, *, stride: int = 1,
                 groups: int = 1, kernel: int = 3) -> None:
        super().__init__(
            nn.Conv2d(in_channels, out_channels, kernel, stride, kernel // 2,
                      groups=groups, bias=False),
            nn.GroupNorm(min(8, out_channels), out_channels),
            nn.GELU(),
        )


def _window_partition(x: Tensor, window: int) -> Tensor:
    batch, height, width, channels = x.shape
    return (x.view(batch, height // window, window, width // window, window, channels)
            .permute(0, 1, 3, 2, 4, 5).reshape(-1, window * window, channels))


def _window_reverse(windows: Tensor, window: int, batch: int,
                    height: int, width: int, channels: int) -> Tensor:
    return (windows.view(batch, height // window, width // window,
                         window, window, channels)
            .permute(0, 1, 3, 2, 4, 5)
            .reshape(batch, height, width, channels))


class WindowAttention(nn.Module):
    def __init__(self, channels: int, heads: int, window: int) -> None:
        super().__init__()
        if channels % heads:
            raise ValueError("channels must be divisible by attention heads")
        self.channels, self.heads, self.window = channels, heads, window
        self.head_dim = channels // heads
        self.scale = self.head_dim ** -0.5
        self.qkv = nn.Linear(channels, channels * 3, bias=True)
        self.projection = nn.Linear(channels, channels)
        self.relative_bias = nn.Parameter(torch.zeros((2 * window - 1) ** 2, heads))
        coords = torch.stack(torch.meshgrid(torch.arange(window), torch.arange(window),
                                            indexing="ij"))
        coords = coords.flatten(1)
        relative = coords[:, :, None] - coords[:, None, :]
        relative = relative.permute(1, 2, 0).contiguous()
        relative[:, :, 0] += window - 1
        relative[:, :, 1] += window - 1
        relative[:, :, 0] *= 2 * window - 1
        self.register_buffer("relative_index", relative.sum(-1), persistent=False)
        nn.init.trunc_normal_(self.relative_bias, std=0.02)

    def forward(self, tokens: Tensor, mask: Tensor | None) -> Tensor:
        batch_windows, count, _ = tokens.shape
        qkv = self.qkv(tokens).reshape(batch_windows, count, 3, self.heads,
                                        self.head_dim).permute(2, 0, 3, 1, 4)
        query, key, value = qkv.unbind(0)
        scores = (query * self.scale) @ key.transpose(-2, -1)
        bias = self.relative_bias[self.relative_index.reshape(-1)]
        bias = bias.view(count, count, self.heads).permute(2, 0, 1)
        scores = scores + bias.unsqueeze(0)
        if mask is not None:
            windows_per_image = mask.shape[0]
            scores = scores.view(-1, windows_per_image, self.heads, count, count)
            scores = scores + mask[None, :, None, :, :]
            scores = scores.flatten(0, 1)
        attended = scores.softmax(-1) @ value
        attended = attended.transpose(1, 2).reshape(batch_windows, count, self.channels)
        return self.projection(attended)


class SwinBlock(nn.Module):
    def __init__(self, channels: int, heads: int, window: int = 4,
                 shifted: bool = False, mlp_ratio: int = 2) -> None:
        super().__init__()
        self.window, self.shifted = window, shifted
        self.norm1 = nn.LayerNorm(channels)
        self.attention = WindowAttention(channels, heads, window)
        self.norm2 = nn.LayerNorm(channels)
        hidden = channels * mlp_ratio
        self.mlp = nn.Sequential(nn.Linear(channels, hidden), nn.GELU(),
                                 nn.Linear(hidden, channels))

    def _shift_mask(self, height: int, width: int, device: torch.device) -> Tensor | None:
        if not self.shifted:
            return None
        window, shift = self.window, self.window // 2
        regions = torch.zeros((1, height, width, 1), device=device)
        h_slices = (slice(0, -window), slice(-window, -shift), slice(-shift, None))
        w_slices = (slice(0, -window), slice(-window, -shift), slice(-shift, None))
        label = 0
        for hs in h_slices:
            for ws in w_slices:
                regions[:, hs, ws, :] = label
                label += 1
        region_windows = _window_partition(regions, window).squeeze(-1)
        difference = region_windows[:, :, None] - region_windows[:, None, :]
        return difference.masked_fill(difference != 0, -100.0).masked_fill(
            difference == 0, 0.0)

    def forward(self, feature: Tensor, spatial_valid: Tensor | None = None) -> Tensor:
        batch, channels, original_h, original_w = feature.shape
        x = feature.permute(0, 2, 3, 1)
        shortcut = x
        x = self.norm1(x)
        if spatial_valid is None:
            valid = torch.ones((batch, original_h, original_w, 1), dtype=x.dtype, device=x.device)
        else:
            valid = spatial_valid.permute(0, 2, 3, 1).to(dtype=x.dtype)
        pad_h = (-original_h) % self.window
        pad_w = (-original_w) % self.window
        if pad_h or pad_w:
            x = F.pad(x, (0, 0, 0, pad_w, 0, pad_h))
            valid = F.pad(valid, (0, 0, 0, pad_w, 0, pad_h))
        _, height, width, _ = x.shape
        if self.shifted:
            shift = self.window // 2
            x = torch.roll(x, shifts=(-shift, -shift), dims=(1, 2))
            valid = torch.roll(valid, shifts=(-shift, -shift), dims=(1, 2))
        windows = _window_partition(x, self.window)
        mask = self._shift_mask(height, width, x.device)
        key_valid = _window_partition(valid, self.window).squeeze(-1) > 0.5
        padding_mask = torch.zeros_like(key_valid[:, :, None], dtype=x.dtype).expand(
            -1, -1, self.window * self.window).clone()
        padding_mask.masked_fill_(~key_valid[:, None, :], -100.0)
        if mask is None:
            mask = padding_mask
        else:
            # Shift masks are shared by all images; padding masks are per image.
            # Expand the former before combining so batch sizes above one work.
            mask = mask.unsqueeze(0).expand(batch, -1, -1, -1).reshape_as(padding_mask)
            mask = mask + padding_mask
        windows = self.attention(windows, mask)
        x = _window_reverse(windows, self.window, batch, height, width, channels)
        if self.shifted:
            x = torch.roll(x, shifts=(self.window // 2, self.window // 2), dims=(1, 2))
        x = x[:, :original_h, :original_w, :]
        x = shortcut + x
        x = x + self.mlp(self.norm2(x))
        return x.permute(0, 3, 1, 2).contiguous()


class SwinStage(nn.Module):
    def __init__(self, channels: int, heads: int, window: int = 4) -> None:
        super().__init__()
        self.blocks = nn.ModuleList((SwinBlock(channels, heads, window, shifted=False),
                                     SwinBlock(channels, heads, window, shifted=True)))

    def forward(self, feature: Tensor, spatial_valid: Tensor) -> Tensor:
        for block in self.blocks:
            feature = block(feature, spatial_valid)
        return feature


class FiLM(nn.Module):
    def __init__(self, context_dim: int, channels: int) -> None:
        super().__init__()
        self.affine = nn.Linear(context_dim, channels * 2)

    def forward(self, x: Tensor, context: Tensor) -> Tensor:
        scale, bias = self.affine(context).chunk(2, dim=1)
        return x * (1.0 + scale[:, :, None, None]) + bias[:, :, None, None]


class SeparableResidual(nn.Module):
    def __init__(self, channels: int, out_channels: int) -> None:
        super().__init__()
        self.depthwise = ConvNormAct(channels, channels, groups=channels)
        self.pointwise = ConvNormAct(channels, out_channels, kernel=1)
        self.skip = nn.Identity() if channels == out_channels else nn.Conv2d(
            channels, out_channels, 1, bias=False)

    def forward(self, x: Tensor) -> Tensor:
        return F.gelu(self.pointwise(self.depthwise(x)) + self.skip(x))


class ContextSwinUNet(nn.Module):
    """Pixel-aligned multi-task network with global item and mod context.

    Image: [B,5,H,W] RGB, alpha and valid-surface mask in [0,1]. Metadata:
    [B,64] stable normalized fields. Name: optional UTF-8 bytes [B,L], zero padded.
    Spatial predictions are at source resolution; only the deterministic compiler
    creates the configured higher-resolution PBR maps.
    """

    def __init__(self, material_classes: int, structure_classes: int,
                 object_classes: int, metal_classes: int, metadata_dim: int = 64,
                 window: int = 4) -> None:
        super().__init__()
        self.stem = ConvNormAct(5, 48)
        self.stage_full = SwinStage(48, heads=3, window=window)
        self.down_half = ConvNormAct(48, 64, stride=2)
        self.stage_half = SwinStage(64, heads=4, window=window)
        self.down_quarter = ConvNormAct(64, 128, stride=2)
        self.stage_quarter = SwinStage(128, heads=4, window=window)
        self.down_eighth = ConvNormAct(128, 192, stride=2)
        self.stage_eighth = SwinStage(192, heads=6, window=window)

        self.image_context = nn.Sequential(nn.Linear(192 + 48, 96), nn.GELU(),
                                           nn.Linear(96, 64), nn.GELU())
        self.metadata_context = nn.Sequential(nn.Linear(metadata_dim, 48), nn.GELU(),
                                              nn.Linear(48, 32), nn.GELU())
        self.name_embedding = nn.Embedding(257, 16, padding_idx=0)
        self.name_encoder = nn.Sequential(nn.Conv1d(16, 24, 3, padding=1), nn.GELU(),
                                          nn.Conv1d(24, 24, 3, padding=1), nn.GELU())
        self.context_features = nn.Linear(64 + 32 + 24, 64)
        self.semantic_condition = nn.Linear(object_classes + material_classes, 64)
        nn.init.zeros_(self.semantic_condition.weight)
        nn.init.zeros_(self.semantic_condition.bias)
        self.context = nn.Sequential(nn.Linear(64, 48), nn.GELU(), nn.Linear(48, 48), nn.GELU())
        global_dim = 64 + 32 + 24
        self.object_type_head = nn.Linear(global_dim, object_classes)
        self.object_material_head = nn.Linear(global_dim, material_classes)

        self.film_eighth = FiLM(48, 192)
        self.decode_quarter = SeparableResidual(192 + 128, 128)
        self.film_quarter = FiLM(48, 128)
        self.decode_half = SeparableResidual(128 + 64, 80)
        self.film_half = FiLM(48, 80)
        self.decode_full = SeparableResidual(80 + 48, 48)
        self.film_full = FiLM(48, 48)

        self.material_head = nn.Conv2d(48, material_classes, 1)
        self.structure_head = nn.Conv2d(48, structure_classes, 1)
        self.boundary_head = nn.Conv2d(48, 2, 1)
        self.base_depth_head = nn.Conv2d(48, 1, 1)
        self.fine_depth_head = nn.Conv2d(48, 1, 1)
        self.smoothness_head = nn.Conv2d(48, 1, 1)
        self.dielectric_f0_head = nn.Conv2d(48, 1, 1)
        self.metal_type_head = nn.Conv2d(48, metal_classes, 1)
        self.ao_head = nn.Conv2d(48, 1, 1)

    def _name_features(self, name_bytes: Tensor, batch: int, device: torch.device) -> Tensor:
        if name_bytes.numel() == 0:
            name_bytes = torch.zeros((batch, 1), dtype=torch.long, device=device)
        encoded = self.name_embedding(name_bytes.clamp(0, 256)).transpose(1, 2)
        return self.name_encoder(encoded).amax(dim=-1)

    def forward(self, image: Tensor, metadata: Tensor,
                name_bytes: Tensor | None = None) -> Prediction:
        batch = image.shape[0]
        if name_bytes is None:
            name_bytes = torch.zeros((batch, 0), dtype=torch.long, device=image.device)
        spatial_valid = image[:, 4:5].clamp(0.0, 1.0)
        full = self.stage_full(self.stem(image), spatial_valid)
        half = self.down_half(full)
        valid_half = F.adaptive_max_pool2d(spatial_valid, half.shape[-2:])
        half = self.stage_half(half, valid_half)
        quarter = self.down_quarter(half)
        valid_quarter = F.adaptive_max_pool2d(spatial_valid, quarter.shape[-2:])
        quarter = self.stage_quarter(quarter, valid_quarter)
        eighth = self.down_eighth(quarter)
        valid_eighth = F.adaptive_max_pool2d(spatial_valid, eighth.shape[-2:])
        eighth = self.stage_eighth(eighth, valid_eighth)
        pooled = torch.cat((F.adaptive_avg_pool2d(eighth, 1).flatten(1),
                            F.adaptive_max_pool2d(full, 1).flatten(1)), dim=1)
        meta = self.metadata_context(metadata)
        name = self._name_features(name_bytes, batch, image.device)
        global_features = torch.cat((self.image_context(pooled), meta, name), dim=1)
        object_type_logits = self.object_type_head(global_features)
        object_material_logits = self.object_material_head(global_features)
        semantic_probabilities = torch.cat((object_type_logits.softmax(dim=1),
                                            object_material_logits.sigmoid()), dim=1)
        context = self.context(self.context_features(global_features) +
                               self.semantic_condition(semantic_probabilities))

        x = self.film_eighth(eighth, context)
        x = F.interpolate(x, size=quarter.shape[-2:], mode="nearest")
        x = self.film_quarter(self.decode_quarter(torch.cat((x, quarter), 1)), context)
        x = F.interpolate(x, size=half.shape[-2:], mode="nearest")
        x = self.film_half(self.decode_half(torch.cat((x, half), 1)), context)
        x = F.interpolate(x, size=full.shape[-2:], mode="nearest")
        x = self.film_full(self.decode_full(torch.cat((x, full), 1)), context)

        return Prediction(
            object_type_logits, object_material_logits,
            self.material_head(x), self.structure_head(x), self.boundary_head(x),
            torch.sigmoid(self.base_depth_head(x)), torch.sigmoid(self.fine_depth_head(x)),
            torch.sigmoid(self.smoothness_head(x)), torch.sigmoid(self.dielectric_f0_head(x)),
            self.metal_type_head(x), torch.sigmoid(self.ao_head(x)))

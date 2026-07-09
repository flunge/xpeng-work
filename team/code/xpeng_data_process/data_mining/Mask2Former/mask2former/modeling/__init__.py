# Copyright (c) Facebook, Inc. and its affiliates.
from .backbone.swin import D2SwinTransformer
from .pixel_decoder.fpn import BasePixelDecoder
from .pixel_decoder.msdeformattn import MSDeformAttnPixelDecoder
from .meta_arch.mask_former_head import MaskFormerHead
from .meta_arch.per_pixel_baseline import PerPixelBaselineHead, PerPixelBaselinePlusHead

_backbone_adapters_imported = False


def ensure_backbone_registered():
    global _backbone_adapters_imported
    if not _backbone_adapters_imported:
        from .backbones_vitAdapter.adapter import D2VitAdapterDinoV2
        from .backbones_samAdapter.adapter import SAMAdapter
        _backbone_adapters_imported = True

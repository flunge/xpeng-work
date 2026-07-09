# Copyright (c) OpenMMLab. All rights reserved.
import warnings

from .sr_backbones import CLIPIQAPredictor, CLIPIQAFixed

__all__ = ['CLIPIQAPredictor', 'CLIPIQAFixed']

try:
    from .encoder_decoders import (VGG16, ContextualAttentionNeck, DeepFillDecoder,
                                   DeepFillEncoder, DeepFillEncoderDecoder,
                                   DepthwiseIndexBlock, FBADecoder,
                                   FBAResnetDilated, GLDecoder, GLDilationNeck,
                                   GLEncoder, GLEncoderDecoder, HolisticIndexBlock,
                                   IndexedUpsample, IndexNetDecoder,
                                   IndexNetEncoder, PConvDecoder, PConvEncoder,
                                   PConvEncoderDecoder, PlainDecoder,
                                   ResGCADecoder, ResGCAEncoder, ResNetDec,
                                   ResNetEnc, ResShortcutDec, ResShortcutEnc,
                                   SimpleEncoderDecoder)
    __all__ += ['VGG16', 'ContextualAttentionNeck', 'DeepFillDecoder', 'DeepFillEncoder',
                'DeepFillEncoderDecoder', 'DepthwiseIndexBlock', 'FBADecoder', 'FBAResnetDilated',
                'GLDecoder', 'GLDilationNeck', 'GLEncoder', 'GLEncoderDecoder', 'HolisticIndexBlock',
                'IndexedUpsample', 'IndexNetDecoder', 'IndexNetEncoder', 'PConvDecoder', 'PConvEncoder',
                'PConvEncoderDecoder', 'PlainDecoder', 'ResGCADecoder', 'ResGCAEncoder', 'ResNetDec',
                'ResNetEnc', 'ResShortcutDec', 'ResShortcutEnc', 'SimpleEncoderDecoder']
except (ImportError, ModuleNotFoundError) as _e:
    warnings.warn(f'Could not import encoder_decoders: {_e}')

try:
    from .generation_backbones import ResnetGenerator, UnetGenerator
    __all__ += ['ResnetGenerator', 'UnetGenerator']
except (ImportError, ModuleNotFoundError) as _e:
    warnings.warn(f'Could not import generation_backbones: {_e}')

try:
    from .sr_backbones import (EDSR, LIIFEDSR, LIIFRDN, RDN, SRCNN, BasicVSRNet,
                               BasicVSRPlusPlus, DICNet, EDVRNet, GLEANStyleGANv2,
                               IconVSR, MSRResNet, RealBasicVSRNet, RRDBNet,
                               TDANNet, TOFlow, TTSRNet)
    __all__ += ['EDSR', 'LIIFEDSR', 'LIIFRDN', 'RDN', 'SRCNN', 'BasicVSRNet',
                'BasicVSRPlusPlus', 'DICNet', 'EDVRNet', 'GLEANStyleGANv2', 'IconVSR',
                'MSRResNet', 'RealBasicVSRNet', 'RRDBNet', 'TDANNet', 'TOFlow', 'TTSRNet']
except (ImportError, ModuleNotFoundError) as _e:
    warnings.warn(f'Could not import some sr_backbones: {_e}')

try:
    from .vfi_backbones import CAINNet, FLAVRNet, TOFlowVFINet
    __all__ += ['CAINNet', 'FLAVRNet', 'TOFlowVFINet']
except (ImportError, ModuleNotFoundError) as _e:
    warnings.warn(f'Could not import vfi_backbones: {_e}')

__all__ = [
    'MSRResNet', 'VGG16', 'PlainDecoder', 'SimpleEncoderDecoder',
    'GLEncoderDecoder', 'GLEncoder', 'GLDecoder', 'GLDilationNeck',
    'PConvEncoderDecoder', 'PConvEncoder', 'PConvDecoder', 'ResNetEnc',
    'ResNetDec', 'ResShortcutEnc', 'ResShortcutDec', 'RRDBNet',
    'DeepFillEncoder', 'HolisticIndexBlock', 'DepthwiseIndexBlock',
    'ContextualAttentionNeck', 'DeepFillDecoder', 'EDSR', 'RDN', 'DICNet',
    'DeepFillEncoderDecoder', 'EDVRNet', 'IndexedUpsample', 'IndexNetEncoder',
    'IndexNetDecoder', 'TOFlow', 'ResGCAEncoder', 'ResGCADecoder', 'SRCNN',
    'UnetGenerator', 'ResnetGenerator', 'FBAResnetDilated', 'FBADecoder',
    'BasicVSRNet', 'IconVSR', 'TTSRNet', 'GLEANStyleGANv2', 'TDANNet',
    'LIIFEDSR', 'LIIFRDN', 'BasicVSRPlusPlus', 'RealBasicVSRNet', 'CAINNet',
    'TOFlowVFINet', 'FLAVRNet', 'CLIPIQAPredictor', 'CLIPIQAFixed'
]

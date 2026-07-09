# Copyright (c) OpenMMLab. All rights reserved.
import warnings

__all__ = []

try:
    from .discriminators import (DeepFillv1Discriminators, GLDiscs, ModifiedVGG,
                                 MultiLayerDiscriminator, PatchDiscriminator,
                                 UNetDiscriminatorWithSpectralNorm)
    __all__ += ['GLDiscs', 'ModifiedVGG', 'MultiLayerDiscriminator',
                'DeepFillv1Discriminators', 'PatchDiscriminator', 'UNetDiscriminatorWithSpectralNorm']
except (ImportError, ModuleNotFoundError) as _e:
    warnings.warn(f'Could not import discriminators: {_e}')

try:
    from .refiners import DeepFillRefiner, PlainRefiner
    __all__ += ['DeepFillRefiner', 'PlainRefiner']
except (ImportError, ModuleNotFoundError) as _e:
    warnings.warn(f'Could not import refiners: {_e}')

try:
    from .stylegan2 import StyleGAN2Discriminator, StyleGANv2Generator
    __all__ += ['StyleGAN2Discriminator', 'StyleGANv2Generator']
except (ImportError, ModuleNotFoundError) as _e:
    warnings.warn(f'Could not import stylegan2: {_e}')

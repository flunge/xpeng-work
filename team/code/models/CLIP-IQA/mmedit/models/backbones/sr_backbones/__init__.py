# Copyright (c) OpenMMLab. All rights reserved.
import warnings

# Always import CLIP-IQA models (no mmcv CUDA ops required)
from .coopclipiqa import CLIPIQAPredictor, CLIPIQAFixed

__all__ = ['CLIPIQAPredictor', 'CLIPIQAFixed']

# Optionally import models that depend on mmcv CUDA extensions
_optional_imports = [
    ('basicvsr_net', ['BasicVSRNet']),
    ('basicvsr_pp', ['BasicVSRPlusPlus']),
    ('dic_net', ['DICNet']),
    ('edsr', ['EDSR']),
    ('edvr_net', ['EDVRNet']),
    ('glean_styleganv2', ['GLEANStyleGANv2']),
    ('iconvsr', ['IconVSR']),
    ('liif_net', ['LIIFEDSR', 'LIIFRDN']),
    ('rdn', ['RDN']),
    ('real_basicvsr_net', ['RealBasicVSRNet']),
    ('rrdb_net', ['RRDBNet']),
    ('sr_resnet', ['MSRResNet']),
    ('srcnn', ['SRCNN']),
    ('tdan_net', ['TDANNet']),
    ('tof', ['TOFlow']),
    ('ttsr_net', ['TTSRNet']),
]

for _module_name, _class_names in _optional_imports:
    try:
        import importlib
        _mod = importlib.import_module(f'.{_module_name}', package=__name__)
        for _cls in _class_names:
            globals()[_cls] = getattr(_mod, _cls)
            __all__.append(_cls)
    except (ImportError, ModuleNotFoundError) as _e:
        warnings.warn(f'Could not import {_class_names} from {_module_name}: {_e}')

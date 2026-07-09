from .xpeng import XpengDataset


def build_dataset(name: str, spec, hparams, kwargs: dict, duplicate_num=1):
    return eval(name)(**kwargs, spec=spec, hparams=hparams, duplicate_num=duplicate_num)
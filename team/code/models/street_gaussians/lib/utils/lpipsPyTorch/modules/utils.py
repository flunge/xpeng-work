from collections import OrderedDict

import torch
import os


def normalize_activation(x, eps=1e-10):
    norm_factor = torch.sqrt(torch.sum(x ** 2, dim=1, keepdim=True))
    return x / (norm_factor + eps)


def get_state_dict(net_type: str = 'alex', version: str = '0.1'):
    print(f"LPIPS_MODEL_PATH {os.environ.get('LPIPS_MODEL_PATH')}")
    local_path = os.environ.get('LPIPS_MODEL_PATH', None)

    if local_path is None:
        # download
        url = 'https://raw.githubusercontent.com/richzhang/PerceptualSimilarity/' \
            + f'master/lpips/weights/v{version}/{net_type}.pth'
        old_state_dict = torch.hub.load_state_dict_from_url(
            url, progress=True,
            map_location=None if torch.cuda.is_available() else torch.device('cpu')
        )
    else:
        old_state_dict = torch.load(
            local_path,
            map_location=None if torch.cuda.is_available() else torch.device('cpu'))

    # rename keys
    new_state_dict = OrderedDict()
    for key, val in old_state_dict.items():
        new_key = key
        new_key = new_key.replace('lin', '')
        new_key = new_key.replace('model.', '')
        new_state_dict[new_key] = val

    return new_state_dict

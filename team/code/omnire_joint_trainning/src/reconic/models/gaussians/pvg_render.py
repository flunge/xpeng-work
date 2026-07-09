"""
Filename: pvg.py

Author: Ziyu Chen (ziyu.sjtu@gmail.com)

Description:
Unofficial implementation of PVG based on the work by Yurui Chen, Chun Gu, Junzhe Jiang, Xiatian Zhu, Li Zhang.

Original paper: https://arxiv.org/abs/2311.18561
"""

import logging
from typing import Dict, List
import torch
from torch.nn import Parameter
from .vanilla_render import VanillaGaussians_render

logger = logging.getLogger()


class PeriodicVibrationGaussians_render(VanillaGaussians_render):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._taus = torch.zeros(1, 1, device=self.device)
        self._betas = torch.zeros(1, 1, device=self.device)
        self._velocity = torch.zeros(1, 3, device=self.device)

        self.T = self.ctrl_cfg.cycle_length
        self.t_grad_accum = None

    def load_state_dict(self, state_dict: Dict, **kwargs) -> str:
        N = state_dict["_means"].shape[0]
        self._means = Parameter(torch.zeros((N,) + self._means.shape[1:], device=self.device))
        self._scales = Parameter(torch.zeros((N,) + self._scales.shape[1:], device=self.device))
        self._quats = Parameter(torch.zeros((N,) + self._quats.shape[1:], device=self.device))
        self._features_dc = Parameter(torch.zeros((N,) + self._features_dc.shape[1:], device=self.device))
        self._features_rest = Parameter(torch.zeros((N,) + self._features_rest.shape[1:], device=self.device))
        self._opacities = Parameter(torch.zeros((N,) + self._opacities.shape[1:], device=self.device))
        self._taus = Parameter(torch.zeros((N,) + self._taus.shape[1:], device=self.device))
        self._betas = Parameter(torch.zeros((N,) + self._betas.shape[1:], device=self.device))
        self._velocity = Parameter(torch.zeros((N,) + self._velocity.shape[1:], device=self.device))
        msg = super().load_state_dict(state_dict, **kwargs)
        return msg

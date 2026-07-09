"""
Optimizers class.
"""
from __future__ import annotations
from abc import abstractmethod

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Type
import numpy as np

import torch
from torch.cuda.amp.grad_scaler import GradScaler
from torch.nn.parameter import Parameter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, List, Literal, Optional, Tuple, Type
from torch.optim import Optimizer, lr_scheduler
try:
    from torch.optim.lr_scheduler import LRScheduler
except ImportError:
    # Backwards compatibility for PyTorch 1.x
    from torch.optim.lr_scheduler import _LRScheduler as LRScheduler

# Pretty printing class
class PrintableConfig:
    def __str__(self):
        lines = [self.__class__.__name__ + ":"]
        for key, val in vars(self).items():
            if isinstance(val, Tuple):
                flattened_val = "["
                for item in val:
                    flattened_val += str(item) + "\n"
                flattened_val = flattened_val.rstrip("\n")
                val = flattened_val + "]"
            lines += f"{key}: {str(val)}".split("\n")
        return "\n    ".join(lines)


@dataclass
class InstantiateConfig(PrintableConfig):
    """Config class for instantiating an the class specified in the _target attribute."""

    _target: Type

    def setup(self, **kwargs) -> Any:
        """Returns the instantiated object using the config."""
        return self._target(self, **kwargs)

@dataclass
class SchedulerConfig(InstantiateConfig):
    """Basic scheduler config"""

    _target: Type = field(default_factory=lambda: Scheduler)
    """target class to instantiate"""

class Scheduler:
    """Base scheduler"""

    config: SchedulerConfig

    def __init__(self, config: SchedulerConfig) -> None:
        super().__init__()
        self.config = config

    @abstractmethod
    def get_scheduler(self, optimizer: Optimizer, lr_init: float) -> LRScheduler:
        """Abstract method that returns a scheduler object.

        Args:
            optimizer: The optimizer to use.
            lr_init: The initial learning rate.
        Returns:
            The scheduler object.
        """

@dataclass
class ExponentialDecaySchedulerConfig(SchedulerConfig):
    """Config for exponential decay scheduler with warmup"""

    _target: Type = field(default_factory=lambda: ExponentialDecayScheduler)
    """target class to instantiate"""
    lr_pre_warmup: float = 1e-8
    """Learning rate before warmup."""
    lr_final: Optional[float] = None
    """Final learning rate. If not provided, it will be set to the optimizers learning rate."""
    warmup_steps: int = 0
    """Number of warmup steps."""
    max_steps: int = 100000
    """The maximum number of steps."""
    ramp: Literal["linear", "cosine"] = "cosine"
    """The ramp function to use during the warmup."""


class ExponentialDecayScheduler(Scheduler):
    """Exponential decay scheduler with linear warmup. Scheduler first ramps up to `lr_init` in `warmup_steps`
    steps, then exponentially decays to `lr_final` in `max_steps` steps.
    """

    config: ExponentialDecaySchedulerConfig

    def get_scheduler(self, optimizer: Optimizer, lr_init: float) -> LRScheduler:
        if self.config.lr_final is None:
            lr_final = lr_init
        else:
            lr_final = self.config.lr_final

        def func(step):
            if step < self.config.warmup_steps:
                if self.config.ramp == "cosine":
                    lr = self.config.lr_pre_warmup + (lr_init - self.config.lr_pre_warmup) * np.sin(
                        0.5 * np.pi * np.clip(step / self.config.warmup_steps, 0, 1)
                    )
                else:
                    lr = (
                        self.config.lr_pre_warmup
                        + (lr_init - self.config.lr_pre_warmup) * step / self.config.warmup_steps
                    )
            else:
                t = np.clip(
                    (step - self.config.warmup_steps) / (self.config.max_steps - self.config.warmup_steps), 0, 1
                )
                lr = np.exp(np.log(lr_init) * (1 - t) + np.log(lr_final) * t)
            return lr / lr_init  # divided by lr_init because the multiplier is with the initial learning rate

        scheduler = lr_scheduler.LambdaLR(optimizer, lr_lambda=func)
        return scheduler

# Optimizer related configs
@dataclass
class OptimizerConfig(PrintableConfig):
    """Basic optimizer config with RAdam"""

    _target: Type = torch.optim.Adam
    """The optimizer class to use."""
    lr: float = 0.0005
    """The learning rate to use."""
    eps: float = 1e-08
    """The epsilon value to use."""
    max_norm: Optional[float] = None
    """The max norm to use for gradient clipping."""

    # TODO: somehow make this more generic. i dont like the idea of overriding the setup function
    # but also not sure how to go about passing things into predefined torch objects.
    def setup(self, params) -> torch.optim.Optimizer:
        """Returns the instantiated object using the config."""
        kwargs = vars(self).copy()
        kwargs.pop("_target")
        kwargs.pop("max_norm")
        return self._target(params, **kwargs)


@dataclass
class AdamOptimizerConfig(OptimizerConfig):
    """Basic optimizer config with Adam"""

    _target: Type = torch.optim.Adam
    weight_decay: float = 0
    """The weight decay to use."""



class Optimizers:
    def __init__(self, config: Dict[str, Any], param_groups: Dict[str, List[Parameter]]) -> None:
        self.config = config
        self.optimizers = {}
        self.schedulers = {}
        self.parameters = {}
        for param_group_name, params in param_groups.items():
            # Print some nice warning messages if the user forgot to specify an optimizer
            if param_group_name not in config:
                raise RuntimeError(
                    f"""Optimizer config for '{param_group_name}' not found in config file. Make sure you specify an optimizer for each parameter group. Provided configs were: {config.keys()}"""
                )
            lr_init = config[param_group_name]["optimizer"].lr
            self.optimizers[param_group_name] = config[param_group_name]["optimizer"].setup(params=params)
            self.parameters[param_group_name] = params
            if config[param_group_name]["scheduler"]:
                self.schedulers[param_group_name] = (
                    config[param_group_name]["scheduler"]
                    .setup()
                    .get_scheduler(optimizer=self.optimizers[param_group_name], lr_init=lr_init)
                )

    def zero_grad_some(self, param_groups: List[str]) -> None:
        """Zero the gradients for the given parameter groups."""
        for param_group in param_groups:
            optimizer = self.optimizers[param_group]
            optimizer.zero_grad()

    def optimizer_scaler_step_some(self, grad_scaler: GradScaler, param_groups: List[str]) -> None:
        """Take an optimizer step using a grad scaler ONLY on the specified param groups.

        Args:
            grad_scaler: GradScaler to use
        """
        for param_group in param_groups:
            optimizer = self.optimizers[param_group]
            # if param_group == "mlp_conv":
            #     print("mlp_conv lr ", optimizer.param_groups[0]["lr"])
            #     optimizer.param_groups[0]["lr"] = 0.0001
                # print("current_lr ", optimizer.param_groups[0]["lr"])

            max_norm = self.config[param_group]["optimizer"].max_norm
            if max_norm is not None:
                grad_scaler.unscale_(optimizer)
                torch.nn.utils.clip_grad_norm_(self.parameters[param_group], max_norm)
            if any(any(p.grad is not None for p in g["params"]) for g in optimizer.param_groups):
                grad_scaler.step(optimizer)

    def scheduler_step_all(self, step: int) -> None:
        """Run step for all schedulers.

        Args:
            step: the current step
        """
        for param_group_name, scheduler in self.schedulers.items():
            scheduler.step()
            # TODO(ethan): clean this up. why is there indexing into a list?
            lr = scheduler.get_last_lr()[0]

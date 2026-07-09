import math
import torch
import numpy as np

import torchsparse
from torch import nn
from torchsparse import nn as spnn
from torchsparse import SparseTensor
from typing import Union, List, Tuple
from torchsparse.nn import Conv3d, BatchNorm, ReLU


class TimeEmbedding(nn.Module):
    def __init__(self, dim):
        super().__init__()
        self.dim = dim
        half_dim = dim // 2
        freqs = torch.exp(torch.arange(half_dim, dtype=torch.float32) * -(math.log(10000.0) / (half_dim - 1)))
        self.register_buffer('freqs', freqs)

    def forward(self, t):
        args = t.unsqueeze(-1) * self.freqs.unsqueeze(0)
        return torch.cat([torch.cos(args), torch.sin(args)], dim=-1)


class SparseConvBlock(nn.Sequential):
    def __init__(
        self,
        in_channels: int,
        out_channels: int,
        kernel_size: Union[int, List[int], Tuple[int, ...]],
        stride: Union[int, List[int], Tuple[int, ...]] = 1,
        dilation: int = 1,
    ) -> None:
        super().__init__(
            spnn.Conv3d(
                in_channels, out_channels, kernel_size, stride=stride, dilation=dilation
            ),
            spnn.BatchNorm(out_channels),
            spnn.ReLU(True),
        )

class SparseConvTransposeBlock(nn.Sequential):
    def __init__(
        self,
        in_channels: int,
        out_channels: int,
        kernel_size: Union[int, List[int], Tuple[int, ...]],
        stride: Union[int, List[int], Tuple[int, ...]] = 1,
        dilation: int = 1,
    ) -> None:
        super().__init__(
            spnn.Conv3d(
                in_channels,
                out_channels,
                kernel_size,
                stride=stride,
                dilation=dilation,
                transposed=True,
            ),
            spnn.BatchNorm(out_channels),
            spnn.ReLU(True),
        )


class SparseResBlock(nn.Module):
    def __init__(
        self,
        in_channels: int,
        out_channels: int,
        kernel_size: Union[int, List[int], Tuple[int, ...]],
        stride: Union[int, List[int], Tuple[int, ...]] = 1,
        dilation: int = 1,
    ) -> None:
        super().__init__()
        self.main = nn.Sequential(
            spnn.Conv3d(
                in_channels, out_channels, kernel_size, dilation=dilation, stride=stride
            ),
            spnn.BatchNorm(out_channels),
            spnn.ReLU(True),
            spnn.Conv3d(out_channels, out_channels, kernel_size, dilation=dilation),
            spnn.BatchNorm(out_channels),
        )

        if in_channels != out_channels or np.prod(stride) != 1:
            self.shortcut = nn.Sequential(
                spnn.Conv3d(in_channels, out_channels, 1, stride=stride),
                spnn.BatchNorm(out_channels),
            )
        else:
            self.shortcut = nn.Identity()

        self.relu = spnn.ReLU(True)

    def forward(self, x: SparseTensor) -> SparseTensor:
        x = self.relu(self.main(x) + self.shortcut(x))
        return x


class SparseResUNet(nn.Module):
    def __init__(
        self,
        stem_channels: int,
        time_embedding_channels: int,
        encoder_channels: List[int],
        decoder_channels: List[int],
        *,
        in_channels: int = 4,
        width_multiplier: float = 1.0,
    ) -> None:
        super().__init__()
        self.stem_channels = stem_channels
        self.encoder_channels = encoder_channels
        self.decoder_channels = decoder_channels
        self.in_channels = in_channels
        self.width_multiplier = width_multiplier

        self.time_embedding_channels = time_embedding_channels
        self.time_embed = TimeEmbedding(time_embedding_channels)

        num_channels = [stem_channels] + encoder_channels + decoder_channels
        num_channels = [int(width_multiplier * nc) for nc in num_channels]

        self.stem = nn.Sequential(
            spnn.Conv3d(in_channels, num_channels[0], 3),
            spnn.BatchNorm(num_channels[0]),
            spnn.ReLU(True),
            spnn.Conv3d(num_channels[0], num_channels[0], 3),
            spnn.BatchNorm(num_channels[0]),
            spnn.ReLU(True),
        )

        self.encoders = nn.ModuleList()
        for k in range(4):
            self.encoders.append(
                nn.Sequential(
                    SparseConvBlock(
                        num_channels[k],
                        num_channels[k],
                        2,
                        stride=2,
                    ),
                    SparseResBlock(num_channels[k], num_channels[k + 1], 3),
                    SparseResBlock(num_channels[k + 1], num_channels[k + 1], 3),
                )
            )

        self.decoders = nn.ModuleList()
        for k in range(4):
            self.decoders.append(
                nn.ModuleDict(
                    {
                        "upsample": SparseConvTransposeBlock(
                            num_channels[k + 4] + (self.time_embedding_channels if k == 0 else 0),
                            num_channels[k + 5],
                            2,
                            stride=2,
                        ),
                        "fuse": nn.Sequential(
                            SparseResBlock(
                                num_channels[k + 5] + num_channels[3 - k],
                                num_channels[k + 5],
                                3,
                            ),
                            SparseResBlock(
                                num_channels[k + 5],
                                num_channels[k + 5],
                                3,
                            ),
                        ),
                    }
                )
            )

    def _unet_forward(
        self,
        x: SparseTensor,
        encoders: nn.ModuleList,
        decoders: nn.ModuleList,
        t_step: torch.Tensor,
    ) -> List[SparseTensor]:
        if not encoders and not decoders:
            time_emb = self.time_embed(t_step).expand(x.feats.shape[0], -1)
            time_emb_sp = SparseTensor(feats=time_emb, coords=x.coords)
            x = torchsparse.cat([x, time_emb_sp])
            return [x]

        # downsample
        xd = encoders[0](x)

        # inner recursion
        outputs = self._unet_forward(xd, encoders[1:], decoders[:-1], t_step)
        yd = outputs[-1]

        u = decoders[-1]["upsample"](yd)
        y = decoders[-1]["fuse"](torchsparse.cat([u, x]))
        return [x] + outputs + [y]

    def forward(self, x: SparseTensor, t_step: torch.Tensor) -> List[SparseTensor]:
        return self._unet_forward(self.stem(x), self.encoders, self.decoders, t_step)

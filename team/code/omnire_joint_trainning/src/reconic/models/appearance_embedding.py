import logging

import torch
from torch import nn

from .modules import Conv1DMLP, PositionalEncoding

logger = logging.getLogger()


class AppearanceEmbeddingModel(nn.Module):
    def __init__(
        self,
        input_feature_dims: int = 16,
        num_cams: int = -1,
        camera_embedding_dims: int = 16,
        num_timesteps: int = -1,
        timestep_embedding_dims: int = 16,
        is_novel_view_dependent: bool = False,
        novel_view_embedding_dims: int = 16,
        is_view_dependent: bool = False,
        num_view_direction_frequencies: int = 3,
    ):
        super(AppearanceEmbeddingModel, self).__init__()

        self.input_feature_dims = input_feature_dims
        self.num_cams = num_cams
        self.camera_embedding_dims = camera_embedding_dims
        self.num_timesteps = num_timesteps
        self.timestep_embedding_dims = timestep_embedding_dims
        self.is_novel_view_dependent = is_novel_view_dependent
        self.novel_view_embedding_dims = novel_view_embedding_dims
        self.is_view_dependent = is_view_dependent
        self.num_view_direction_frequencies = num_view_direction_frequencies
        self.computed_appearance_embedding = {} # key: (camera_id, novel_view), value: appearance_embedding
        self.use_cache = not self.is_view_dependent

        input_dims = self.input_feature_dims

        if self.num_cams > 0:
            # camera ID learnable embedding
            self.camera_embedding = nn.Embedding(
                num_embeddings=self.num_cams,
                embedding_dim=self.camera_embedding_dims,
            )
            input_dims += self.camera_embedding_dims

        if self.num_timesteps > 0:
            # timestep learnable embedding
            self.timestep_embedding = nn.Embedding(
                num_embeddings=self.num_timesteps,
                embedding_dim=self.timestep_embedding_dims,
            )
            input_dims += self.timestep_embedding_dims

        if self.is_novel_view_dependent:
            # novel view learnable embedding
            self.novel_view_embedding = nn.Embedding(
                num_embeddings=2,
                embedding_dim=self.novel_view_embedding_dims,
            )
            input_dims += self.novel_view_embedding_dims

        if self.is_view_dependent:
            # view direction positional encoding
            self.view_direction_encoding = PositionalEncoding(3, self.num_view_direction_frequencies)
            input_dims += self.view_direction_encoding.get_output_n_channels()

        self.network = Conv1DMLP(
            input_channels=input_dims,
            output_channels=3,
            channels=[64, 32],
            activation="SiLU",
            output_activation="tanh",
            kernel_size=1,
        )

        self.weight_init()

    def weight_init(self):
        if self.num_cams > 0:
            torch.nn.init.zeros_(self.camera_embedding.weight)
        if self.num_timesteps > 0:
            torch.nn.init.zeros_(self.timestep_embedding.weight)
        if self.is_novel_view_dependent:
            torch.nn.init.zeros_(self.novel_view_embedding.weight)

    def forward(
        self,
        appearance_features: torch.Tensor,
        camera_id: torch.Tensor,
        timestep_id: torch.Tensor,
        viewdirs: torch.Tensor,
        is_novel_view: torch.Tensor,
        test_mode: bool = False,
    ) -> torch.Tensor:
        if self.use_cache and test_mode:
            search_key = (camera_id.item(), is_novel_view.item())
            if search_key in self.computed_appearance_embedding:
                return self.computed_appearance_embedding[search_key]

        input_tensor_list = [appearance_features]
        if self.num_cams > 0:
            camera_embeddings = self.camera_embedding(camera_id.reshape((-1,))).repeat(appearance_features.shape[0], 1)
            input_tensor_list.append(camera_embeddings)

        if self.num_timesteps > 0:
            timestep_embeddings = self.timestep_embedding(timestep_id.reshape((-1,))).repeat(
                appearance_features.shape[0], 1
            )
            input_tensor_list.append(timestep_embeddings)

        if self.is_novel_view_dependent:
            view_embeddings = self.novel_view_embedding(is_novel_view).repeat(appearance_features.shape[0], 1)
            input_tensor_list.append(view_embeddings)

        if self.is_view_dependent:
            input_tensor_list.append(self.view_direction_encoding(viewdirs))

        network_input = torch.concat(input_tensor_list, dim=-1)
        output = self.network(network_input)

        if self.use_cache and test_mode:
            self.computed_appearance_embedding[search_key] = output

        return output

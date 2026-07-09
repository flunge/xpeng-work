import numpy as np
import torch
from torch import nn
from ..utility.geometry import createHiveFlatMesh, cutHiveMeshWithPoses, createMultiResolutionMesh
from pytorch3d.structures import Meshes
from pytorch3d.renderer import TexturesVertex
import scipy
from tqdm import tqdm
import time
import cv2
import os


def clean_nan(grad):
    grad = torch.nan_to_num_(grad)
    return grad


class HeightMLP(nn.Module):
    def __init__(self, num_encoding, num_width):
        super().__init__()
        self.num_encoding = num_encoding
        self.D = num_width
        self.pos_channel = 2 * (2 * self.num_encoding + 1)
        self.height_layer_0 = nn.Sequential(
            nn.Linear(self.pos_channel, self.D), nn.ReLU(),
            nn.Linear(self.D, self.D), nn.ReLU(),
            nn.Linear(self.D, self.D), nn.ReLU(),
            nn.Linear(self.D, self.D), nn.ReLU(),
        )
        self.height_layer_1 = nn.Sequential(
            nn.Linear(self.D + self.pos_channel, self.D), nn.ReLU(),
            nn.Linear(self.D, self.D), nn.ReLU(),
            nn.Linear(self.D, self.D), nn.ReLU(),
            nn.Linear(self.D, 1),
        )

    def encode_position(self, input, levels, include_input=True):
        """
        For each scalar, we encode it using a series of sin() and cos() functions with different frequency.
            - With L pairs of sin/cos function, each scalar is encoded to a vector that has 2L elements. Concatenating with
            itself results in 2L+1 elements.
            - With C channels, we get C(2L+1) channels output.

        :param input:   (..., C)            torch.float32
        :param levels:  scalar L            int
        :return:        (..., C*(2L+1))     torch.float32
        """

        # this is already doing "log_sampling" in the official code.
        result_list = [input] if include_input else []
        for i in range(levels):
            temp = 2.0**i * input  # (..., C)
            result_list.append(torch.sin(temp))  # (..., C)
            result_list.append(torch.cos(temp))  # (..., C)

        result_list = torch.cat(result_list, dim=-1)  # (..., C*(2L+1)) The list has (2L+1) elements, with (..., C) shape each.
        return result_list  # (..., C*(2L+1))

    def forward(self, norm_xy):
        encoded_norm_xy = self.encode_position(norm_xy, levels=self.num_encoding)
        feature_z = self.height_layer_0(encoded_norm_xy)
        vertices_z = self.height_layer_1(torch.cat([feature_z, encoded_norm_xy], dim=-1))
        return vertices_z


class FeatureMLP(nn.Module):
    def __init__(self, num_encoding, num_width, num_feature):
        super().__init__()
        self.num_encoding = num_encoding
        self.num_feature = num_feature
        self.D = num_width
        self.pos_channel = 2 * (2 * self.num_encoding + 1)
        self.height_layer_0 = nn.Sequential(
            nn.Linear(self.pos_channel + self.num_feature, self.D), nn.ReLU(),
            nn.Linear(self.D, self.D), nn.ReLU(),
            nn.Linear(self.D, self.D), nn.ReLU(),
            nn.Linear(self.D, self.D), nn.ReLU(),
        )
        self.height_layer_1 = nn.Sequential(
            nn.Linear(self.D + self.pos_channel + self.num_feature, self.D), nn.ReLU(),
            nn.Linear(self.D, self.D), nn.ReLU(),
            nn.Linear(self.D, self.D), nn.ReLU(),
            nn.Linear(self.D, 1),
        )

    def encode_position(self, input, levels, include_input=True):
        """
        For each scalar, we encode it using a series of sin() and cos() functions with different frequency.
            - With L pairs of sin/cos function, each scalar is encoded to a vector that has 2L elements. Concatenating with
            itself results in 2L+1 elements.
            - With C channels, we get C(2L+1) channels output.

        :param input:   (..., C)            torch.float32
        :param levels:  scalar L            int
        :return:        (..., C*(2L+1))     torch.float32
        """

        # this is already doing "log_sampling" in the official code.
        result_list = [input] if include_input else []
        for i in range(levels):
            temp = 2.0**i * input  # (..., C)
            result_list.append(torch.sin(temp))  # (..., C)
            result_list.append(torch.cos(temp))  # (..., C)

        result_list = torch.cat(result_list, dim=-1)  # (..., C*(2L+1)) The list has (2L+1) elements, with (..., C) shape each.
        return result_list  # (..., C*(2L+1))

    def forward(self, norm_xy, feature):
        encoded_norm_xy = self.encode_position(norm_xy, levels=self.num_encoding)
        encoded_xy_feature = torch.cat([encoded_norm_xy, feature], dim=-1)
        feature_z = self.height_layer_0(encoded_xy_feature)
        vertices_z = self.height_layer_1(torch.cat([feature_z, encoded_xy_feature], dim=-1))
        return vertices_z


class SquareFlatGridBase(nn.Module):
    def __init__(self, bev_x_length, bev_y_length, pose_xy, resolution, cut_range, bev_seg_image_path=None, new_resolution=0.02):
        super().__init__()
        self.bev_x_length = bev_x_length
        self.bev_y_length = bev_y_length
        self.resolution = resolution
        if bev_seg_image_path is None:
            vertices, faces, self.bev_size_pixel = createHiveFlatMesh(bev_x_length, bev_y_length, resolution)
            print(f"Before cutting: {vertices.shape[0]} vertices, {faces.shape[0]} faces")
            vertices, faces, self.bev_size_pixel = cutHiveMeshWithPoses(vertices, faces, self.bev_size_pixel,
                                                                        bev_x_length, bev_y_length, pose_xy,
                                                                        resolution, cut_range)
            print(f"After cutting: {vertices.shape[0]} vertices, {faces.shape[0]} faces")
        else:
            self.resolution = new_resolution
            vertices, faces = createMultiResolutionMesh(bev_seg_image_path, resolution, new_resolution)
            print(f"multi resolution mesh, {vertices.shape[0]} vertices, {faces.shape[0]} faces")

        self.texture = None
        self.mesh = None
        norm_x = vertices[:, 0]/self.bev_x_length * 2 - 1
        norm_y = vertices[:, 1]/self.bev_y_length * 2 - 1
        norm_xy = torch.cat([norm_x[:, None], norm_y[:, None]], dim=1)
        self.register_buffer('norm_xy', norm_xy)
        self.register_buffer('vertices', vertices)
        self.register_buffer('faces', faces)

    def init_vertices_z(self):
        with torch.no_grad():
            self.vertices_z = torch.zeros((self.norm_xy.shape[0], 1), device=self.norm_xy.device) # No need to change for base class
            # norm_y = self.norm_xy[:, 0]
            # norm_y[norm_y < 0.1] = 0
            # vertices_z = torch.pow(norm_y, 0.5) * 0.2
            # vertices_z = torch.clamp(vertices_z, 0, 1).unsqueeze(1)
            # vertices_z *= -1
            self.vertices = torch.cat((self.vertices[:, :2], self.vertices_z), dim=1)

    def init_vertices_rgb(self):
        self.vertices_rgb = nn.Parameter(torch.zeros_like(self.vertices)[None])

    def freeze_vertices_z(self, z):
        with torch.no_grad():
            self.vertices_z = torch.from_numpy(z).to(self.norm_xy.device) # No need to change for base class
            self.vertices = torch.cat((self.vertices[:, :2], self.vertices_z), dim=1)

    def freeze_vertices_rgb(self, rgb):
        del self.vertices_rgb
        with torch.no_grad():
            self.vertices_rgb = nn.Parameter(torch.from_numpy(rgb)[None].to(self.norm_xy.device)) # No need to change for base class

class SquareFlatGridRGB(SquareFlatGridBase):
    def __init__(self, configs, pose_xy, num_classes=None):
        if "bev_seg_path" not in configs:
            super().__init__(configs["bev_x_length"], configs["bev_y_length"], pose_xy, configs["bev_resolution"], configs["cut_range"])
        else:
            super().__init__(configs["bev_x_length"], configs["bev_y_length"], pose_xy, configs["old_bev_resolution"], configs["cut_range"], configs["bev_seg_path"], configs["bev_resolution"])
        self.vertices_rgb = nn.Parameter(torch.zeros_like(self.vertices)[None])

    def forward(self, batch_size=1):
        constrained_vertices_rgb = (torch.tanh(self.vertices_rgb) + 1)/2
        self.texture = TexturesVertex(verts_features=constrained_vertices_rgb)
        self.mesh = Meshes(verts=[self.vertices], faces=[self.faces], textures=self.texture)
        return self.mesh.extend(batch_size)


class SquareFlatGridLabel(SquareFlatGridBase):
    def __init__(self, configs, pose_xy, num_classes=None):
        if "bev_seg_path" not in configs:
            super().__init__(configs["bev_x_length"], configs["bev_y_length"], pose_xy, configs["bev_resolution"], configs["cut_range"])
        else:
            super().__init__(configs["bev_x_length"], configs["bev_y_length"], pose_xy, configs["old_bev_resolution"], configs["cut_range"], configs["bev_seg_path"], configs["bev_resolution"])
        num_vertices = self.vertices.shape[0]
        self.vertices_label = nn.Parameter(torch.zeros((1, num_vertices, num_classes), dtype=torch.float32))

    def forward(self, batch_size=1):
        softmax_vertices_label = torch.softmax(self.vertices_label, dim=-1)
        self.texture = TexturesVertex(verts_features=softmax_vertices_label)
        self.mesh = Meshes(verts=[self.vertices], faces=[self.faces], textures=self.texture)
        return self.mesh.extend(batch_size)


class SquareFlatGridRGBLabel(SquareFlatGridBase):
    def __init__(self, configs, pose_xy, num_classes=None):
        if "bev_seg_path" not in configs:
            super().__init__(configs["bev_x_length"], configs["bev_y_length"], pose_xy, configs["bev_resolution"], configs["cut_range"])
        else:
            super().__init__(configs["bev_x_length"], configs["bev_y_length"], pose_xy, configs["old_bev_resolution"], configs["cut_range"], configs["bev_seg_path"], configs["bev_resolution"])
        num_vertices = self.vertices.shape[0]
        self.vertices_rgb = nn.Parameter(torch.zeros_like(self.vertices)[None])
        self.vertices_label = nn.Parameter(torch.zeros((1, num_vertices, num_classes), dtype=torch.float32))

    def forward(self, batch_size=1):
        # constrained_vertices_rgb = (torch.tanh(self.vertices_rgb) + 1)/2
        constrained_vertices_rgb = self.vertices_rgb
        # norm_xy = self.norm_xy.clone()
        # norm_x = norm_xy[:, 0].unsqueeze(0)
        # norm_x = torch.clamp((norm_x + 1) / 2, 0, 1)
        # constrained_vertices_rgb[:, :, 0] = torch.pow((1 - norm_x), 0.5)
        # constrained_vertices_rgb[:, :, 1] = torch.pow((1 - norm_x), 0.5)
        # constrained_vertices_rgb[:, :, 2] = torch.pow((1 - norm_x), 0.5)

        softmax_vertices_label = torch.softmax(self.vertices_label, dim=-1)
        features = torch.cat((constrained_vertices_rgb, softmax_vertices_label), dim=-1)
        self.texture = TexturesVertex(verts_features=features)
        self.mesh = Meshes(verts=[self.vertices], faces=[self.faces], textures=self.texture)
        return self.mesh.extend(batch_size)


class SquareFlatGridBaseZ(nn.Module):
    def __init__(self, bev_x_length, bev_y_length, pose_xy, resolution, num_encoding=2, cut_range=30, bev_seg_image_path=None, new_resolution=0.02):
        super().__init__()
        self.bev_x_length = bev_x_length
        self.bev_y_length = bev_y_length
        self.resolution = resolution
        if bev_seg_image_path is None:
            vertices, faces, self.bev_size_pixel = createHiveFlatMesh(bev_x_length, bev_y_length, resolution)
            print(f"Before cutting,  {vertices.shape[0]} vertices, {faces.shape[0]} faces")
            vertices, faces, self.bev_size_pixel = cutHiveMeshWithPoses(vertices, faces, self.bev_size_pixel,
                                                                        bev_x_length, bev_y_length, pose_xy,
                                                                        resolution, cut_range)
            print(f"After cutting,  {vertices.shape[0]} vertices, {faces.shape[0]} faces")
        else:
            self.resolution = new_resolution
            vertices, faces = createMultiResolutionMesh(bev_seg_image_path, resolution, new_resolution)
            print(f"multi resolution mesh, {vertices.shape[0]} vertices, {faces.shape[0]} faces")

        self.texture = None
        self.mesh = None
        self.register_buffer('faces', faces)
        self.mlp = HeightMLP(num_encoding=num_encoding, num_width=128)
        norm_x = vertices[:, 0]/self.bev_x_length * 2 - 1
        norm_y = vertices[:, 1]/self.bev_y_length * 2 - 1
        norm_xy = torch.cat([norm_x[:, None], norm_y[:, None]], dim=1)
        self.register_buffer('norm_xy', norm_xy) ### vertices coordinates that have been normalized to [-1, 1]
        self.register_buffer('vertices_xy', vertices[:, :2])

    def get_activation_idx(self, center_xy, radius):
        distance = np.linalg.norm(self.vertices_xy.detach().cpu().numpy() - center_xy, ord=np.inf, axis=1)
        activation_idx = list(np.where(distance <= radius)[0])
        return activation_idx

    def init_vertices_z(self, pose_xyz, use_guassian=True):
        with torch.no_grad():
            vertices_z = torch.zeros((self.norm_xy.shape[0], 1))
            print('assign initial z value for vertices')
            prior_vertices_z = torch.zeros((self.norm_xy.shape[0], 1))
            kdtree = scipy.spatial.KDTree(data=pose_xyz[:, :2], copy_data=True)

            if not use_guassian:
                vertices_xy_cpu = self.vertices_xy.cpu().numpy()
                for i in tqdm(range(vertices_xy_cpu.shape[0])):
                    tgt_point = vertices_xy_cpu[i]
                    distance, index = kdtree.query(tgt_point, k=1)
                    v_z = float(pose_xyz[index][-1])
                    prior_vertices_z[i] = v_z
            else:
                start_time = time.time()
                resolution = self.resolution
                scale = 1.0 / resolution
                heatmap_size = np.ceil(self.vertices_xy.detach().cpu().numpy().max(0) * scale).astype(int) + 1
                heatmap = np.zeros(heatmap_size, dtype=float)
                vertices_xy_cpu = self.vertices_xy.cpu().numpy()

                # Vectorized assignment
                x_coords, y_coords = np.round(vertices_xy_cpu[:, :2] * scale).astype(int).T
                heatmap[x_coords, y_coords] = 1.0

                kernal_size = int(scale * 5.0)
                heatmap = cv2.dilate(heatmap, np.ones((kernal_size, kernal_size), dtype=int), iterations=1)

                # Vectorized query and assignment
                x_coords, y_coords = np.where(heatmap == 1.0)
                points = np.column_stack((x_coords * resolution, y_coords * resolution))
                distances, indices = kdtree.query(points, k=1)
                heatmap[x_coords, y_coords] = pose_xyz[indices, 2]

                smoothed_heatmap = scipy.ndimage.gaussian_filter(heatmap, sigma=10, radius=int(kernal_size * 0.5))

                # Vectorized final assignment
                x_coords, y_coords = np.round(vertices_xy_cpu[:, :2] * scale).astype(int).T
                prior_vertices_z = torch.tensor(smoothed_heatmap[x_coords, y_coords]).unsqueeze(1).float()

                print('Initial mesh prior_z timecost: {:.3f}s'.format(time.time() - start_time))

            # using buffer for cuda operation
            self.register_buffer('vertices_z', vertices_z)
            self.register_buffer('prior_vertices_z', prior_vertices_z)

    def init_prior_vertices_z(self, prior_vertices_z):
        vertices_z = torch.zeros((self.norm_xy.shape[0], 1))
        self.register_buffer('vertices_z', vertices_z)
        self.register_buffer('prior_vertices_z', prior_vertices_z)


class SquareFlatGridRGBZ(SquareFlatGridBaseZ):
    def __init__(self, configs, pose_xy, num_classes=None, num_encoding=2):
        if "bev_seg_path" not in configs:
            super().__init__(configs["bev_x_length"], configs["bev_y_length"], pose_xy, configs["bev_resolution"], num_encoding, configs["cut_range"])
        else:
            super().__init__(configs["bev_x_length"], configs["bev_y_length"], pose_xy, configs["old_bev_resolution"], num_encoding, configs["cut_range"], configs["bev_seg_path"], configs["bev_resolution"])
        num_vertices = self.vertices_xy.shape[0]
        self.vertices_rgb = nn.Parameter(torch.zeros(num_vertices, 3)[None])

    def forward(self, activated_idx=None, batch_size=1):
        constrained_vertices_rgb = (torch.tanh(self.vertices_rgb) + 1)/2
        if activated_idx is None:
            vertices_z = self.mlp(self.norm_xy)
            vertices_xy = self.vertices_xy
        else:
            activtated_norm_xy = self.norm_xy[activated_idx]
            activated_vertices_z = self.mlp(activtated_norm_xy)
            if activated_vertices_z.requires_grad:
                activated_vertices_z.register_hook(clean_nan)
            with torch.no_grad():
                self.vertices_z[activated_idx] = activated_vertices_z
                vertices_z = self.vertices_z.detach()
            vertices_z[activated_idx] = activated_vertices_z

            # activtated_vertices_xy = self.vertices_xy[activated_idx]
            # if activtated_vertices_xy.requires_grad:
            #     activtated_vertices_xy.register_hook(clean_nan)
            # with torch.no_grad():
            #     self.vertices_xy[activated_idx] = activtated_vertices_xy
            #     vertices_xy = self.vertices_xy.detach()
            # vertices_xy[activated_idx] = activtated_vertices_xy

        vertices = torch.cat((self.vertices_xy, vertices_z), dim=1)
        self.texture = TexturesVertex(verts_features=constrained_vertices_rgb)
        self.mesh = Meshes(verts=[vertices], faces=[self.faces], textures=self.texture)
        return self.mesh.extend(batch_size)


class SquareFlatGridLabelZ(SquareFlatGridBaseZ):
    def __init__(self, configs, pose_xy, num_classes, num_encoding=2):
        if "bev_seg_path" not in configs:
            super().__init__(configs["bev_x_length"], configs["bev_y_length"], pose_xy, configs["bev_resolution"], num_encoding, configs["cut_range"])
        else:
            super().__init__(configs["bev_x_length"], configs["bev_y_length"], pose_xy, configs["old_bev_resolution"], num_encoding, configs["cut_range"], configs["bev_seg_path"], configs["bev_resolution"])
        num_vertices = self.vertices_xy.shape[0]
        self.vertices_label = nn.Parameter(torch.zeros((1, num_vertices, num_classes), dtype=torch.float32))

    def forward(self, activated_idx=None, batch_size=1):
        softmax_vertices_label = torch.softmax(self.vertices_label, dim=-1)
        if activated_idx is None:
            vertices_z = self.mlp(self.norm_xy)
        else:
            activtated_norm_xy = self.norm_xy[activated_idx]
            activated_vertices_z = self.mlp(activtated_norm_xy)
            if activated_vertices_z.requires_grad:
                activated_vertices_z.register_hook(clean_nan)
            with torch.no_grad():
                self.vertices_z[activated_idx] = activated_vertices_z
                vertices_z = self.vertices_z.detach()
            vertices_z[activated_idx] = activated_vertices_z
        vertices = torch.cat((self.vertices_xy, vertices_z), dim=1)
        self.texture = TexturesVertex(verts_features=softmax_vertices_label)
        self.mesh = Meshes(verts=[vertices], faces=[self.faces], textures=self.texture)
        return self.mesh.extend(batch_size)


class SquareFlatGridRGBLabelZ(SquareFlatGridBaseZ):
    def __init__(self, configs, pose_xy, num_classes, num_encoding=2, z_scale=1.0):
        if "bev_seg_path" not in configs:
            super().__init__(configs["bev_x_length"], configs["bev_y_length"], pose_xy, configs["bev_resolution"], num_encoding, configs["cut_range"])
        else:
            super().__init__(configs["bev_x_length"], configs["bev_y_length"], pose_xy, configs["old_bev_resolution"], num_encoding, configs["cut_range"], configs["bev_seg_path"], configs["bev_resolution"])
        num_vertices = self.vertices_xy.shape[0]
        self.vertices_rgb = nn.Parameter(torch.zeros(num_vertices, 3)[None])
        self.vertices_label = nn.Parameter(torch.zeros((1, num_vertices, num_classes), dtype=torch.float32))
        self.z_scale = z_scale

    def forward(self, activated_idx=None, batch_size=1, is_init=False):
        constrained_vertices_rgb = (torch.tanh(self.vertices_rgb) + 1)/2
        softmax_vertices_label = torch.softmax(self.vertices_label, dim=-1)
        features = torch.cat((constrained_vertices_rgb, softmax_vertices_label), dim=-1)
        if is_init:
            vertices_z = self.prior_vertices_z
        else:
            vertices_z = self.vertices_z.detach()
            vertices_z = torch.tanh(self.mlp(self.norm_xy)) * self.z_scale + self.prior_vertices_z
            if vertices_z.requires_grad:
                vertices_z.register_hook(clean_nan)

        vertices = torch.cat((self.vertices_xy, vertices_z), dim=1)
        self.texture = TexturesVertex(verts_features=features)
        self.mesh = Meshes(verts=[vertices], faces=[self.faces], textures=self.texture)
        return self.mesh.extend(batch_size)

    @torch.no_grad()
    def get_verts_features(self):
        vertices_z = torch.tanh(self.mlp(self.norm_xy)) * self.z_scale + self.prior_vertices_z
        constrained_vertices_rgb = (torch.tanh(self.vertices_rgb) + 1)/2
        softmax_vertices_label = torch.softmax(self.vertices_label, dim=-1)
        verts_features = torch.cat([self.vertices_xy, vertices_z, constrained_vertices_rgb.squeeze(0), softmax_vertices_label.squeeze(0)], dim=-1)

        return verts_features
import json
import os

import cv2
import numpy as np
import pymeshlab
import torch
from pytorch3d.io import save_obj
from pytorch3d.renderer import MeshRasterizer, RasterizationSettings
from pytorch3d.renderer.cameras import OrthographicCameras
from torch import nn

from ..utility.renderer import SimpleShader
import matplotlib.pyplot as plt
from ..utility.misc import draw_trip_trajectory


def mesh2height(mesh, bev_size_pixel):
    z_tensor = mesh._verts_list[0][:, 2]
    z_tensor = z_tensor.reshape(bev_size_pixel)
    return z_tensor


def loss2color(loss):
    min, max = loss.min(), loss.max()
    if (max - min) < 1e-7:
        loss = np.zeros_like(loss)
    else:
        # normalize depth by min max
        loss = (loss - min) / (max - min)
        loss.clip(0, 1)
    # convert to rgb
    loss = (loss * 255).astype(np.uint8)
    loss_rgb = cv2.applyColorMap(loss, cv2.COLORMAP_HOT)
    # BGR to RGB
    loss_rgb = cv2.cvtColor(loss_rgb, cv2.COLOR_BGR2RGB)
    return loss_rgb


def depth2color(depth, min, max, rescale=False):
    # normalize depth by min max
    depth = (depth - min) / (max - min)
    depth = depth.clip(0, 1)
    if rescale:
        depth = np.sqrt(depth)
    # convert to rgb
    depth = (depth * 255).astype(np.uint8)
    # depth_rgb = cv2.applyColorMap(depth, cv2.COLORMAP_HOT)
    depth_rgb = cv2.applyColorMap(depth, cv2.COLORMAP_JET)
    # BGR to RGB
    depth_rgb = cv2.cvtColor(depth_rgb, cv2.COLOR_BGR2RGB)
    return depth_rgb

def depth2color_plt(depth, min, max):
    scaled_depth_map = (depth - min) / (max - min)
    scaled_depth_map = scaled_depth_map.clip(0, 1)

    h, w = depth.shape
    fig = plt.figure(dpi=200)
    fig.add_subplot(111)
    plt.imshow(scaled_depth_map, cmap='jet')  # You can use other colormaps like 'viridis', 'plasma', 'inferno', etc.
    plt.axis('off')
    cbar = plt.colorbar(label='Depth')
    cbar.ax.invert_yaxis()
    fig.canvas.draw()
    data = np.frombuffer(fig.canvas.tostring_rgb(), dtype=np.uint8)
    data = data.reshape(fig.canvas.get_width_height()[::-1] + (3,))

    return data

def save_mesh(mesh, path, bev_size_pixel):
    assert path.endswith(".obj"), "path must be a obj file"
    with torch.no_grad():
        verts = mesh._verts_list[0].detach().cpu()
        faces = mesh._faces_list[0].detach().cpu()
        texture_w, texture_h = bev_size_pixel
        # texture_w, texture_h = 501, 501
        textures = mesh.textures._verts_features_list[0].reshape(texture_w, texture_h, 3).detach().cpu()
        w, h = torch.meshgrid(torch.arange(texture_w, dtype=verts.dtype), torch.arange(texture_h, dtype=verts.dtype))
        verts_uvs = torch.cat((h.unsqueeze(-1) / texture_h, texture_w - 1 - w.unsqueeze(-1) / texture_w),
                              dim=-1).reshape(-1, 2)
        save_obj(path, verts=verts, faces=faces, verts_uvs=verts_uvs, faces_uvs=faces, texture_map=textures)


def save_cut_mesh(mesh, path):
    assert path.endswith(".obj"), "path must be a obj file"
    with torch.no_grad():
        verts = mesh._verts_list[0].detach().cpu().numpy()
        faces = mesh._faces_list[0].detach().cpu().numpy()
        vert_colors = mesh.textures._verts_features_list[0][:, :3].detach().cpu().numpy()
        vert_colors = np.concatenate([vert_colors, np.ones((vert_colors.shape[0], 1))], axis=-1)
        m = pymeshlab.Mesh(vertex_matrix=verts, face_matrix=faces, v_color_matrix=vert_colors)
        ms = pymeshlab.MeshSet()
        ms.add_mesh(m, "vcolor_mesh")
        # save the mesh
        ms.save_current_mesh(path)


def save_cut_label_mesh(mesh, path, color_map):
    assert path.endswith(".obj"), "path must be a obj file"
    with torch.no_grad():
        verts = mesh._verts_list[0].detach().cpu().numpy()
        faces = mesh._faces_list[0].detach().cpu().numpy()
        vert_labels = mesh.textures._verts_features_list[0][:, 3:].detach().cpu().numpy()
        vert_labels = vert_labels.argmax(axis=1)
        np.save(path.replace(".obj", ".npy"), vert_labels)
        vert_colors = np.zeros((vert_labels.shape[0], 3))
        for i in range(vert_labels.shape[0]):
            vert_colors[i] = color_map[vert_labels[i]]
        vert_colors = (vert_colors / 255.0).astype(np.float32)
        vert_colors = np.concatenate([vert_colors, np.ones((vert_colors.shape[0], 1))], axis=-1)
        assert verts.shape[0] == vert_labels.shape[0], "verts and vert_labels must have the same number of vertices"
        m = pymeshlab.Mesh(vertex_matrix=verts, face_matrix=faces, v_color_matrix=vert_colors)
        ms = pymeshlab.MeshSet()
        ms.add_mesh(m, "vcolor_mesh")
        # save the mesh
        ms.save_current_mesh(path)


def save_mesh(mesh, transform, path):
    assert path.endswith(".obj"), "path must be a obj file"
    with torch.no_grad():
        verts = mesh._verts_list[0].detach().cpu().numpy()
        verts = transform[:3, :3] @ verts.transpose() + transform[:3, 3]
        faces = mesh._faces_list[0].detach().cpu().numpy()
        vert_colors = mesh.textures._verts_features_list[0][:, :3].detach().cpu().numpy()
        vert_colors = np.concatenate([vert_colors, np.ones((vert_colors.shape[0], 1))], axis=-1)
        m = pymeshlab.Mesh(vertex_matrix=verts.transpose(), face_matrix=faces, v_color_matrix=vert_colors)
        ms = pymeshlab.MeshSet()
        ms.add_mesh(m, "vcolor_mesh")
        # save the mesh
        ms.save_current_mesh(path)


class MeshRendererWithDepth(nn.Module):

    def __init__(self, rasterizer, shader):
        super().__init__()
        self.rasterizer = rasterizer
        self.shader = shader

    def forward(self, meshes_world, **kwargs) -> torch.Tensor:
        fragments = self.rasterizer(meshes_world, **kwargs)
        images = self.shader(fragments, meshes_world, **kwargs)
        return images, fragments.zbuf


class Visualizer(nn.Module):

    def __init__(self, device, configs):
        super().__init__()
        self.device = device
        self.configs = configs

        image_size = (self.configs["bev_y_pixel"], self.configs["bev_x_pixel"])
        rotation = torch.from_numpy(np.asarray([
            [-1, 0, 0],
            [0, 1, 0],
            [0, 0, 1],
        ], dtype=np.float32))[None]
        cx = self.configs["bev_x_length"] / 2
        cy = self.configs["bev_y_length"] / 2
        translation = torch.from_numpy(np.asarray([cx, -cy, 0.0], dtype=np.float32))[None]
        image_size_tensor = torch.from_numpy(np.asarray(image_size, dtype=np.float32))[None]
        camera = OrthographicCameras(
            focal_length=1.0 / min(cx, cy),
            R=rotation,
            T=translation,
            image_size=image_size_tensor,
            device=device,
        )

        raster_settings = RasterizationSettings(
            image_size=image_size,
            blur_radius=0.0,
            faces_per_pixel=1,
        )
        self.mesh_renderer = MeshRendererWithDepth(
            rasterizer=MeshRasterizer(
                cameras=camera,
                raster_settings=raster_settings,
            ),
            shader=SimpleShader(),
        )

    def forward(self, mesh):
        z_shift = torch.min(mesh.verts_padded()[..., -1]) - 0.1
        self.mesh_renderer.rasterizer.cameras.T[..., -1] = -z_shift
        image, depth = self.mesh_renderer(mesh)
        depth[..., -1] = depth[..., -1] + z_shift
        return image, depth


def draw_input_pose(configs, dataset):
    """
    Draw the trajectory and elevation of each input trip.
    """
    ### Get lists of input image paths and poses
    all_img_poses = dataset.ref_camera2world_all
    all_img_paths = dataset.image_filenames_all
    trip_info = json.load(open(configs["trips_json"], 'r'))
    fig, ax = plt.subplots(2, 1, figsize=(10, 20), dpi=100)

    for trip_path in trip_info.keys():
        ### Get paths and poses of the reference camera of the current trip
        curr_img_paths, curr_trip_poses = [], []
        for i, img_path in enumerate(all_img_paths):
            if trip_path in img_path and configs["ref_cam"] in img_path:
                curr_img_paths.append(all_img_paths[i])
                curr_trip_poses.append(all_img_poses[i])
        if len(curr_trip_poses) <= 1:
            continue

        ### Sort poses by slice index
        zip_path_pose = list(zip(curr_img_paths, curr_trip_poses))
        zip_path_pose = sorted(zip_path_pose, key=lambda x: int(x[0].split(".png")[0].split("slice")[-1]))
        curr_trip_poses = [pose for (path, pose) in zip_path_pose]
        curr_trip_poses = np.stack(curr_trip_poses)
        curr_trip_xy = curr_trip_poses[:, 0:2, 3]
        curr_trip_z = curr_trip_poses[:, 2, 3]

        ### Draw xy and z separately
        slice_idxs = list(range(len(curr_trip_z)))
        trip_name = trip_path.split("image/")[1]
        color = np.random.rand(3)
        draw_trip_trajectory(ax[0], trip_name, curr_trip_xy, color)
        ax[1].plot(slice_idxs, curr_trip_z, color=color, label=trip_name)

    if configs["mode"] == "recon":
        save_path = configs["exp_dir"]
    elif configs["mode"] == "reloc":
        save_path = configs["reloc_dir"]
    else:
        raise ValueError(f"Invalid mode: {configs['mode']}")

    ax[0].legend()
    ax[0].set_title('ROME input trajectory')
    ax[0].set_xlabel("X")
    ax[0].set_ylabel("Y")
    ax[0].axis('equal')
    ax[1].legend()
    ax[1].set_title('ROME input elevation')
    ax[1].set_xlabel("Slice index")
    ax[1].set_ylabel("Z")
    ax[1].grid()
    plt.savefig(os.path.join(save_path, "rome_input_pose.png"))
    plt.close(fig)

    ego_pose_xyz = dataset.ego_pose_xyz[:, :3, 3].transpose()
    title = "trajectory_heatmap"
    fig = plt.figure(title)
    sc = plt.scatter(ego_pose_xyz[0], ego_pose_xyz[1], c=ego_pose_xyz[2], s=1, cmap="jet")
    plt.colorbar(sc)
    plt.title(title)
    plt.axis("equal")
    plt.savefig(os.path.join(save_path, f"{title}.png"), dpi=200)
    plt.close(fig)


def draw_trajectory(bev_rgb, dataset, configs, epoch):
    scale = 1.0 / configs["bev_resolution"]
    world2bev_xy = dataset.world2bev[:2, 3]
    image = bev_rgb.copy()

    ### Write text on image
    bev_size = np.array(bev_rgb.shape[:2]) * configs["bev_resolution"]
    cv2.putText(image, '{:.1f}x{:.1f}'.format(bev_size[1], bev_size[0]), (20, 20), cv2.FONT_HERSHEY_SIMPLEX, 0.5,
                (0, 0, 1), 1, cv2.LINE_AA)
    cv2.putText(image, f'epoch: {epoch}', (20, 40), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 1), 1, cv2.LINE_AA)

    cam_str = 'cam'
    for cam_name in configs['cam_list']:
        cam_str += cam_name.split('cam')[-1]
    cv2.putText(image, cam_str, (20, 60), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 1), 1, cv2.LINE_AA)

    ### Draw trajectory trip by trip
    trips_info = json.load(open(configs['trips_json'], 'r'))
    for trip_path in trips_info.keys():
        trajectory = []
        for idx, img_path in enumerate(dataset.image_filenames_all):
            if trip_path in img_path and configs["ref_cam"] in img_path:
                trajectory.append(dataset.ref_camera2world_all[idx][:2, 3])
        if len(trajectory) <= 1:
            continue

        ### Draw trajectory points
        trajectory = np.array(trajectory) + world2bev_xy
        trajectory *= scale
        trajectory[:,1] = bev_rgb.shape[0] - trajectory[:,1]
        trajectory = np.round(trajectory).astype(np.int32)
        for pt in trajectory:
            cv2.circle(image, pt, radius=1, color=(1, 0, 0), thickness=-1)

        ### Draw trajectory arrows
        arrow_start = None
        arrow_end = trajectory[-1]
        for i in range(2, len(trajectory)):
            if np.linalg.norm(trajectory[-i] - arrow_end) > 1:
                arrow_start = trajectory[-i]
                break
        if arrow_start is not None:
            image = cv2.arrowedLine(image, arrow_start, arrow_end, color=(1,0,0), thickness=1, tipLength=3)

    return image


def save_mesh_depth_height_map(verts, ego_pose_xyz, output_dir, title):
    fig = plt.figure(title)

    verts = verts.squeeze().transpose(0, 1)
    sc = plt.scatter(verts[0], verts[1], c=verts[2], cmap='jet')
    plt.colorbar(sc)

    xyz = ego_pose_xyz.transpose()
    plt.plot(xyz[0], xyz[1], '.', markersize=1, color='black')
    plt.axis('equal')
    plt.title(title)
    plt.savefig(os.path.join(output_dir, f"{title}.png"), dpi=200)
    plt.close(fig)


def bev_image_to_mesh_world(bev_points, configs):
    world_points = np.copy(bev_points)
    world_points[:, 1]  = configs["bev_y_pixel"] - world_points[:, 1]
    world_points = world_points * configs["bev_resolution"]

    return world_points
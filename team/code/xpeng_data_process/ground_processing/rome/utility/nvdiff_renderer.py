import nvdiffrast.torch as nvdiff
import torch

_device2glctx = {}


def _get_nvdiff_glctx(device):
    if device not in _device2glctx:
        _device2glctx[device] = nvdiff.RasterizeCudaContext(device=device)
    return _device2glctx[device]


def tile_based_rasterize(full_image_size, pos, face_indices, tile_size):
    num_tile = torch.ceil(full_image_size / tile_size).to(torch.int32)
    glctx = _get_nvdiff_glctx(pos.device)

    resolution = 2.0 / full_image_size
    stitch_rast = None
    for i in range(num_tile[0]):
        col_stitch_rast = None
        for j in range(num_tile[1]):
            image_size = torch.clamp((full_image_size - tile_size * torch.tensor([i, j])), 0, tile_size)
            center = (tile_size * torch.tensor([i, j]) + image_size * 0.5) * resolution - torch.ones(2)

            new_pos = pos.clone()
            new_pos[..., :2] += center.flip(0).to(new_pos.device)
            new_pos[..., :2] *= (full_image_size / image_size).flip(0).to(new_pos.device)
            new_pos[new_pos[..., 0].abs() > 1.0][..., -1] = 0
            new_pos[new_pos[..., 1].abs() > 1.0][..., -1] = 0
            rast, _ = nvdiff.rasterize(glctx, new_pos, face_indices, image_size, grad_db=False)

            if col_stitch_rast is None:
                col_stitch_rast = rast
            else:
                col_stitch_rast = torch.cat([rast, col_stitch_rast], dim=-2)
        if stitch_rast is None:
            stitch_rast = col_stitch_rast
        else:
            stitch_rast = torch.cat([col_stitch_rast, stitch_rast], dim=-3)

    return stitch_rast


def rasterize(image_size, verts_ndc, face_indices, vert_features, verts_valid):
    glctx = _get_nvdiff_glctx(verts_ndc.device)
    pos = torch.cat([verts_ndc, verts_valid], dim=-1)
    z_max = abs(verts_ndc[..., -1]).max()
    pos[..., -2] = -pos[..., -2] / (z_max + 1e-6)

    tile_size = 2048.0
    if torch.any(image_size > tile_size):
        rast = tile_based_rasterize(image_size, pos, face_indices, tile_size)
    else:
        rast, _ = nvdiff.rasterize(glctx, pos, face_indices, image_size, grad_db=False)
    color, _ = nvdiff.interpolate(vert_features.contiguous(), rast, face_indices)
    # color = nvdiff.antialias(color, rast, pos, face_indices)
    verts_z = verts_ndc[..., -1].contiguous()[..., None]
    image_depth, _ = nvdiff.interpolate(verts_z, rast, face_indices)

    face_idx = (rast[..., -1].long() - 1).contiguous()

    image_depth[face_idx < 0] = -1.0
    image_depth[image_depth < 0.01] = -1.0

    color[face_idx < 0] = 1.0
    color = torch.clamp(color, 0.0, 1.0)

    return color, image_depth, face_idx


class NvdiffRenderer(torch.nn.Module):

    def __init__(self):
        super().__init__()
        self.znear = 0.01
        self.zfar = 200.0

    def forward(self, render_params):
        meshes_world = render_params["mesh"]
        image_size = render_params["image_shape"]
        verts_world = meshes_world.verts_padded()
        world_to_view = render_params["world2camera"].clone().to(torch.float64)
        world_to_view[:, :3, :3] = world_to_view[:, :3, :3].permute(0, 2, 1)
        world_to_view[:, 3, :3] = world_to_view[:, :3, 3]
        world_to_view[:, :3, 3] = 0.0

        proj_matrix = torch.zeros_like(world_to_view, dtype=torch.float64, device=verts_world.device)
        proj_matrix[:, 0, 0] = render_params["focal_length"][:, 0]
        proj_matrix[:, 1, 1] = render_params["focal_length"][:, 1]
        camera_model = render_params.get("camera_model", "perspective")
        if camera_model == "perspective":
            proj_matrix[:, 2, 0] = render_params["principal_point"][:, 0]
            proj_matrix[:, 2, 1] = render_params["principal_point"][:, 1]
            proj_matrix[:, 2, 3] = 1.0
            proj_matrix[:, 3, 2] = 1.0
        elif camera_model == "orthographic":
            proj_matrix[:, 3, 0] = render_params["principal_point"][:, 0]
            proj_matrix[:, 3, 1] = render_params["principal_point"][:, 1]
            proj_matrix[:, 2, 2] = 1.0
            proj_matrix[:, 3, 3] = 1.0

        verts_world_homo = torch.cat(
            [verts_world,
             torch.ones([*verts_world.shape[:-1], 1], dtype=verts_world.dtype, device=verts_world.device)],
            dim=-1).to(torch.float64)
        verts_view = verts_world_homo.bmm(world_to_view)
        batch_verts_ndc = verts_view.bmm(proj_matrix)
        batch_verts_ndc = batch_verts_ndc[..., :3] / batch_verts_ndc[..., 3:]
        batch_verts_ndc[..., 2] = verts_view[..., 2]
        batch_verts_ndc = batch_verts_ndc.to(torch.float32)

        batch_faces = meshes_world.faces_padded()
        batch_features = meshes_world.textures.verts_features_padded()

        verts_valid = torch.logical_and(
            torch.logical_and(batch_verts_ndc[..., 0].abs() < 1.0, batch_verts_ndc[..., 1].abs() < 1.0),
            batch_verts_ndc[..., 2] > self.znear)

        image_features, image_depth, face_idx = rasterize(
            image_size[0],
            batch_verts_ndc,
            batch_faces[0].to(torch.int32),
            batch_features,
            verts_valid.unsqueeze(-1),
        )
        silhouette = torch.where(face_idx < 0, 0, 1)
        image_features = torch.cat([image_features, silhouette.unsqueeze(-1)], -1)

        return image_features, image_depth

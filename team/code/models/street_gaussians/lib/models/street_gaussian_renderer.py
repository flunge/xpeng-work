import torch
import gsplat

from lib.utils.sh_utils import eval_sh
from lib.models.street_gaussian_model import StreetGaussianModel
from lib.utils.camera_utils import Camera, make_rasterizer
from lib.config import cfg


class StreetGaussianRenderer():
    def __init__(
        self,         
    ):
        self.cfg = cfg.render
              
    def render_all(
        self, 
        viewpoint_camera: Camera,
        pc: StreetGaussianModel,
        convert_SHs_python = None, 
        compute_cov3D_python = None, 
        scaling_modifier = None, 
        override_color = None
    ):
        # render all
        render_composition = self.render(
            viewpoint_camera, pc, convert_SHs_python, compute_cov3D_python, scaling_modifier, override_color
        )

        result = render_composition

        # render background
        if pc.include_background:
            render_background = self.render_background(
                viewpoint_camera, pc, convert_SHs_python, compute_cov3D_python, scaling_modifier, override_color
            )
            result['rgb_background'] = render_background['rgb']
            result['acc_background'] = render_background['acc']

        if pc.include_ground:
            render_ground = self.render_ground(
                viewpoint_camera, pc, convert_SHs_python, compute_cov3D_python, scaling_modifier, override_color
            )
            result['rgb_ground'] = render_ground['rgb']
            result['acc_ground'] = render_ground['acc']

        # render object
        render_object = self.render_object(
            viewpoint_camera, pc, convert_SHs_python, compute_cov3D_python, scaling_modifier, override_color
        )
        result['rgb_object'] = render_object['rgb']
        result['acc_object'] = render_object['acc']        
        
        # result['bboxes'], result['bboxes_input'] = pc.get_bbox_corner(viewpoint_camera)
        return result
    
    def render_object(
        self, 
        viewpoint_camera: Camera,
        pc: StreetGaussianModel,
        convert_SHs_python = None, 
        compute_cov3D_python = None, 
        scaling_modifier = None, 
        override_color = None
    ):        
        pc.set_visibility(include_list=pc.obj_list)
        pc.parse_camera(viewpoint_camera, is_render=True)
        
        result = self.render_kernel(viewpoint_camera, pc, convert_SHs_python, compute_cov3D_python, scaling_modifier, override_color, white_background=True)

        return result
    
    def render_background(
        self, 
        viewpoint_camera: Camera,
        pc: StreetGaussianModel,
        convert_SHs_python = None, 
        compute_cov3D_python = None, 
        scaling_modifier = None, 
        override_color = None
    ):
        pc.set_visibility(include_list=['background'])
        pc.parse_camera(viewpoint_camera, is_render=True)
        result = self.render_kernel(viewpoint_camera, pc, convert_SHs_python, compute_cov3D_python, scaling_modifier, override_color, white_background=True)

        return result

    def render_ground(
        self, 
        viewpoint_camera: Camera,
        pc: StreetGaussianModel,
        convert_SHs_python = None, 
        compute_cov3D_python = None, 
        scaling_modifier = None, 
        override_color = None
    ):
        pc.set_visibility(include_list=['ground'])
        pc.parse_camera(viewpoint_camera, is_render=True)
        result = self.render_kernel(viewpoint_camera, pc, convert_SHs_python, compute_cov3D_python, scaling_modifier, override_color, white_background=True)

        return result

    def render_sky(
        self, 
        viewpoint_camera: Camera,
        pc: StreetGaussianModel,
        convert_SHs_python = None, 
        compute_cov3D_python = None, 
        scaling_modifier = None, 
        override_color = None
    ):  
        pc.set_visibility(include_list=['sky'])
        pc.parse_camera(viewpoint_camera, is_render=True)
        result = self.render_kernel(viewpoint_camera, pc, convert_SHs_python, compute_cov3D_python, scaling_modifier, override_color)
        return result
    
    def render(
        self, 
        viewpoint_camera: Camera,
        pc: StreetGaussianModel,
        convert_SHs_python = None, 
        compute_cov3D_python = None, 
        scaling_modifier = None, 
        override_color = None,
        exclude_list = [],
    ):   
        include_list = list(set(pc.model_name_id.keys()) - set(exclude_list))
        
        # Step1: render foreground
        pc.set_visibility(include_list)
        pc.parse_camera(viewpoint_camera, is_render=True)
        
        result = self.render_kernel(
            viewpoint_camera, pc, convert_SHs_python, compute_cov3D_python, scaling_modifier, override_color
        )

        # Step2: render sky
        if pc.include_sky:
            try:
                sky_color = pc.sky_cubemap(viewpoint_camera, result['acc'].detach())
            except Exception as e:
                print(f"[ERROR] {e} for sky rendering in {viewpoint_camera.meta['timestamp']} and cam {viewpoint_camera.meta['cam']}")
            else:
                result['rgb'] = result['rgb'] + sky_color * (1 - result['acc'])

        if pc.use_color_correction:
            result['rgb'] = pc.color_correction(viewpoint_camera, result['rgb'])

        if cfg.mode != 'train':
            result['rgb'] = torch.clamp(result['rgb'], 0., 1.)

        return result
    
    def render_harmonized(
        self, 
        viewpoint_camera: Camera,
        pc: StreetGaussianModel,
        convert_SHs_python = None, 
        compute_cov3D_python = None, 
        scaling_modifier = None, 
        override_color = None,
        exclude_list = [],
    ):  
        include_list = list(set(pc.model_name_id.keys()) - set(exclude_list))
        dynamic_obj_pc = pc
                    
        # Step1: render foreground
        pc.set_visibility(include_list)
        pc.parse_camera(viewpoint_camera, is_render=True)
        
        result = self.render_kernel(
            viewpoint_camera, pc, convert_SHs_python, compute_cov3D_python, scaling_modifier, override_color
        )

        # Step3: render dynamic objects masks
        dynamic_obj_pc.set_visibility(include_list=pc.obj_list)
        dynamic_obj_pc.parse_camera_dynamic_objects(viewpoint_camera, is_render=True)
        mask_result = self.render_kernel(
            viewpoint_camera, dynamic_obj_pc, convert_SHs_python, compute_cov3D_python, scaling_modifier, override_color, white_background=False
        )
        result['rgb_mask'] = mask_result['rgb']

    def render_kernel(self, *args, **kwargs):
        if not cfg.train.get('use_gsplat', False):  # cfg.mode == 'train' and 
            return self.render_kernel_diff_gaus_raster(*args, **kwargs)
        else:
            return self.render_kernel_gsplat(*args, **kwargs)

    def render_kernel_diff_gaus_raster(
        self, 
        viewpoint_camera: Camera,
        pc: StreetGaussianModel,
        convert_SHs_python = None, 
        compute_cov3D_python = None, 
        scaling_modifier = None, 
        override_color = None,
        white_background = cfg.data.white_background,
    ):
        if pc.num_gaussians == 0:
            if white_background:
                rendered_color = torch.ones(3, int(viewpoint_camera.image_height), int(viewpoint_camera.image_width), device="cuda")
            else:
                rendered_color = torch.zeros(3, int(viewpoint_camera.image_height), int(viewpoint_camera.image_width), device="cuda")
            
            rendered_acc = torch.zeros(1, int(viewpoint_camera.image_height), int(viewpoint_camera.image_width), device="cuda")
            rendered_semantic = torch.zeros(0, int(viewpoint_camera.image_height), int(viewpoint_camera.image_width), device="cuda")
            
            return {
                "rgb": rendered_color,
                "acc": rendered_acc,
                "semantic": rendered_semantic,
            }

        # Set up rasterization configuration and make rasterizer
        bg_color = [1, 1, 1] if white_background else [0, 0, 0]
        bg_color = torch.tensor(bg_color).float().cuda()
        scaling_modifier = scaling_modifier or self.cfg.scaling_modifier
        rasterizer = make_rasterizer(viewpoint_camera, pc.max_sh_degree, bg_color, scaling_modifier)
        
        convert_SHs_python = convert_SHs_python or self.cfg.convert_SHs_python
        compute_cov3D_python = compute_cov3D_python or self.cfg.compute_cov3D_python

        # Create zero tensor. We will use it to make pytorch return gradients of the 2D (screen-space) means
        # screenspace_points = torch.zeros_like(pc.get_xyz, dtype=pc.get_xyz.dtype, requires_grad=True, device="cuda") + 0
        if cfg.mode == 'train':
            screenspace_points = torch.zeros((pc.num_gaussians, 3), requires_grad=True).float().cuda() + 0
            try:
                screenspace_points.retain_grad()
            except:
                pass
        else:
            screenspace_points = None 

        means3D = pc.get_xyz
        means2D = screenspace_points
        opacity = pc.get_opacity

        # If precomputed 3d covariance is provided, use it. If not, then it will be computed from
        # scaling / rotation by the rasterizer.
        scales = None
        rotations = None
        cov3D_precomp = None
        if compute_cov3D_python:
            cov3D_precomp = pc.get_covariance(scaling_modifier)
        else:
            scales = pc.get_scaling
            rotations = pc.get_rotation

        # If precomputed colors are provided, use them. Otherwise, if it is desired to precompute colors
        # from SHs in Python, do it. If not, then SH -> RGB conversion will be done by rasterizer.
        shs = None
        colors_precomp = None
        if override_color is None:
            if convert_SHs_python:
                shs_view = pc.get_features.transpose(1, 2).view(-1, 3, (pc.max_sh_degree+1)**2)
                dir_pp = (pc.get_xyz - viewpoint_camera.camera_center.repeat(pc.get_features.shape[0], 1))
                dir_pp_normalized = dir_pp / dir_pp.norm(dim=1, keepdim=True)
                sh2rgb = eval_sh(pc.active_sh_degree, shs_view, dir_pp_normalized)
                colors_precomp = torch.clamp_min(sh2rgb + 0.5, 0.0)
            else:
                try:
                    shs = pc.get_features
                except:
                    colors_precomp = pc.get_colors(viewpoint_camera.camera_center)
        else:
            colors_precomp = override_color

        # TODO: add more feature here
        feature_names = []
        feature_dims = []
        features = []
        
        if cfg.render.render_normal:
            normals = pc.get_normals(viewpoint_camera)
            feature_names.append('normals')
            feature_dims.append(normals.shape[-1])
            features.append(normals)

        if cfg.data.get('use_semantic', False):
            semantics = pc.get_semantic
            feature_names.append('semantic')
            feature_dims.append(semantics.shape[-1])
            features.append(semantics)
        
        if len(features) > 0:
            features = torch.cat(features, dim=-1)
        else:
            features = None
        
        # Rasterize visible Gaussians to image, obtain their radii (on screen). 
        rendered_color, radii, rendered_depth, rendered_acc, rendered_feature = rasterizer(
            means3D = means3D,
            means2D = means2D,
            opacities = opacity,
            shs = shs,
            colors_precomp = colors_precomp,
            scales = scales,
            rotations = rotations,
            cov3D_precomp = cov3D_precomp,
            semantics = features,
        )  
        
        if cfg.mode != 'train':
            rendered_color = torch.clamp(rendered_color, 0., 1.)
        
        rendered_feature_dict = dict()
        if rendered_feature.shape[0] > 0:
            rendered_feature_list = torch.split(rendered_feature, feature_dims, dim=0)
            for i, feature_name in enumerate(feature_names):
                rendered_feature_dict[feature_name] = rendered_feature_list[i]
        
        if 'normals' in rendered_feature_dict:
            rendered_feature_dict['normals'] = torch.nn.functional.normalize(rendered_feature_dict['normals'], dim=0)
                
        if 'semantic' in rendered_feature_dict:
            rendered_semantic = rendered_feature_dict['semantic']
            semantic_mode = cfg.model.gaussian.get('semantic_mode', 'logits')
            assert semantic_mode in ['logits', 'probabilities']
            if semantic_mode == 'logits': 
                pass # return raw semantic logits
            else:
                rendered_semantic = rendered_semantic / (torch.sum(rendered_semantic, dim=0, keepdim=True) + 1e-8) # normalize to probabilities
                rendered_semantic = torch.log(rendered_semantic + 1e-8) # change for cross entropy loss

            rendered_feature_dict['semantic'] = rendered_semantic
        
        # Those Gaussians that were frustum culled or had a radius of 0 were not visible.
        # They will be excluded from value updates used in the splitting criteria.
        if cfg.optim.get('squeeze_grd_gs', False):
            means3D_bkgd = pc.background.get_xyz
            scales_bkgd = pc.background.get_scaling
            rotations_bkgd = pc.background.get_rotation
            radii_bkgd, means2D_bkgd = rasterizer.visible_filter(means3D_bkgd, scales_bkgd, rotations_bkgd)
            means2D_bkgd[radii_bkgd <= 0] = -1
        else:
            means2D_bkgd = None

        result = {
            "rgb": rendered_color,
            "acc": rendered_acc,
            "depth": rendered_depth,
            "viewspace_points": screenspace_points,
            "visibility_filter" : radii > 0,
            "radii": radii,
            "means2D_bkgd": means2D_bkgd
        }
        
        result.update(rendered_feature_dict)
        
        return result
    
    def render_kernel_gsplat(
        self, 
        viewpoint_camera: Camera,
        pc: StreetGaussianModel,
        convert_SHs_python = None, 
        compute_cov3D_python = None, 
        scaling_modifier = None, 
        override_color = None,
        white_background = cfg.data.white_background,
    ):
        
        if pc.num_gaussians == 0:
            if white_background:
                rendered_color = torch.ones(3, int(viewpoint_camera.image_height), int(viewpoint_camera.image_width), device="cuda")
            else:
                rendered_color = torch.zeros(3, int(viewpoint_camera.image_height), int(viewpoint_camera.image_width), device="cuda")
            
            rendered_acc = torch.zeros(1, int(viewpoint_camera.image_height), int(viewpoint_camera.image_width), device="cuda")
            
            return {
                "rgb": rendered_color,
                "acc": rendered_acc,
            }

        # Set up rasterization configuration and make rasterizer
        bg_color = [1, 1, 1] if white_background else [0, 0, 0]
        bg_color = torch.tensor(bg_color).float().cuda()
        
        scaling_modifier = scaling_modifier or self.cfg.scaling_modifier
        convert_SHs_python = convert_SHs_python or self.cfg.convert_SHs_python
        compute_cov3D_python = compute_cov3D_python or self.cfg.compute_cov3D_python

        means3D = pc.get_xyz
        opacity = pc.get_opacity

        # If precomputed 3d covariance is provided, use it. If not, then it will be computed from
        # scaling / rotation by the rasterizer.
        scales = None
        rotations = None
        cov3D_precomp = None
        if compute_cov3D_python:
            cov3D_precomp = pc.get_covariance(scaling_modifier)
        else:
            scales = pc.get_scaling
            rotations = pc.get_rotation

        # If precomputed colors are provided, use them. Otherwise, if it is desired to precompute colors
        # from SHs in Python, do it. If not, then SH -> RGB conversion will be done by rasterizer.
        shs = None
        colors_precomp = None
        if override_color is None:
            if convert_SHs_python:
                shs_view = pc.get_features.transpose(1, 2).view(-1, 3, (pc.max_sh_degree+1)**2)
                dir_pp = (pc.get_xyz - viewpoint_camera.camera_center.repeat(pc.get_features.shape[0], 1))
                dir_pp_normalized = dir_pp / dir_pp.norm(dim=1, keepdim=True)
                sh2rgb = eval_sh(pc.active_sh_degree, shs_view, dir_pp_normalized)
                colors_precomp = torch.clamp_min(sh2rgb + 0.5, 0.0)
            else:
                try:
                    shs = pc.get_features
                except:
                    colors_precomp = pc.get_colors(viewpoint_camera.camera_center)
        else:
            colors_precomp = override_color
        
        render_mode = 'RGB+ED' if cfg.mode == 'train' else 'RGB'
        absgrad = True if cfg.mode == 'train' else False
        rasterize_mode = 'classic' if cfg.mode == 'train' else 'antialiased'
        
        # Rasterize visible Gaussians to image, obtain their radii (on screen). 
        render_colors, render_alphas, meta = gsplat.rasterization(
            means=means3D, # [P, 3]
            quats=rotations, # [P, 4]
            scales=scales, # [P, 3]
            opacities=opacity.squeeze(dim=-1), # [P] # not [P, 1]
            colors=(shs if colors_precomp is None else colors_precomp), # [P, 3] or [P, M (num of sh coefficients), 3]
            covars=cov3D_precomp, # [P, 3, 3] or None
            viewmats=viewpoint_camera.RT.float().unsqueeze(dim=0), #  The world-to-cam transformation of the cameras.  [4, 4]
            Ks=viewpoint_camera.K.unsqueeze(dim=0), # camera intrinsics [3, 3]
            width=viewpoint_camera.image_width,
            height=viewpoint_camera.image_height,
            radius_clip=0.0, #  radius smaller or equal than this value will be skipped. for speeding up large scale scenes. TODO: experiment
            sh_degree=pc.max_sh_degree,
            near_plane=viewpoint_camera.znear,
            far_plane=viewpoint_camera.zfar,
            tile_size=8,
            backgrounds=bg_color.unsqueeze(dim=0), # [3]
            render_mode=render_mode,
            rasterize_mode=rasterize_mode, # 'classic' or 'antialiased'
            camera_model='pinhole',
            packed=False,
            absgrad=absgrad,
        )
                
        render_alphas = render_alphas[0].permute(2, 0, 1)
        radii = meta['radii'][0].squeeze(-1)
        
        if cfg.mode == 'train':
            rendered_color, rendered_depth = torch.split(render_colors[0], [3, 1], dim=-1)
            rendered_color = rendered_color.permute(2, 0, 1)  # [3, H, W]
            rendered_depth = rendered_depth.permute(2, 0, 1)
            try:
                meta['means2d'].retain_grad()
            except:
                pass
        else:
            rendered_color = torch.clamp(render_colors[0].permute(2, 0, 1), 0., 1.)
            rendered_depth = None

        result = {
            "rgb": rendered_color,
            "acc": render_alphas,
            "depth": rendered_depth,
            "viewspace_points": meta['means2d'],
            "visibility_filter" : torch.all(radii > 0, dim=-1),
            "radii": radii,
        }
        return result
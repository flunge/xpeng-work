import torch
import torch.nn as nn
from lib.config import cfg
from lib.utils.camera_utils import Camera
from lib.utils.general_utils import get_expon_lr_func, matrix_to_axis_angle

class ColorCorrection(nn.Module):
    def __init__(self, metadata):
        super().__init__()
        self.identity_matrix = torch.eye(4).float().cuda()[:3] # [3, 4]
        
        self.config = cfg.model.color_correction
        self.mode = self.config.mode
        
        # per image embedding
        if self.mode == 'image':
            num_corrections = metadata['num_images']
        # per sensor embedding
        elif self.mode == 'sensor':
            num_corrections = metadata['num_cams']
        else:
            raise ValueError(f'Invalid mode: {self.mode}')

        if self.config.use_mlp:
            input_ch = 6
            dim = 64
            self.affine_trans = nn.Sequential( 
                nn.Linear(input_ch, dim),
                nn.ReLU(),
                nn.Linear(dim, dim),
                nn.ReLU(),
                nn.Linear(dim, dim),
                nn.ReLU(),
                nn.Linear(dim, 12),
            )
            self.affine_trans[6].weight.data.fill_(0)
            self.affine_trans[6].bias.data.fill_(0)
            self.affine_trans.cuda()
            self.affine_trans_sky = nn.Sequential( 
                nn.Linear(input_ch, dim),
                nn.ReLU(),
                nn.Linear(dim, dim),
                nn.ReLU(),
                nn.Linear(dim, dim),
                nn.ReLU(),
                nn.Linear(dim, 12),
            )
            self.affine_trans_sky[6].weight.data.fill_(0)
            self.affine_trans_sky[6].bias.data.fill_(0)
            self.affine_trans_sky.cuda()
        else:
            self.affine_trans = nn.Parameter(torch.eye(4).float().cuda()[:3].unsqueeze(0).repeat(num_corrections, 1, 1)).requires_grad_(True)
            self.affine_trans_sky = nn.Parameter(torch.eye(4).float().cuda()[:3].unsqueeze(0).repeat(num_corrections, 1, 1)).requires_grad_(True)
        
        self.cur_affine_trans = None

    def save_state_dict(self, is_final):
        state_dict = dict()
        state_dict['params'] = self.state_dict()
        if not is_final:
            state_dict['optimizer'] = self.optimizer.state_dict()
        return state_dict
        
    def load_state_dict(self, state_dict):
        super().load_state_dict(state_dict['params'])
        if cfg.mode == 'train' and 'optimizer' in state_dict:
            self.optimizer.load_state_dict(state_dict['optimizer'])

    def training_setup(self):
        args = cfg.optim
        color_correction_lr_init = args.get('color_correction_lr_init', 5e-4)
        color_correction_lr_final = args.get('color_correction_lr_final', 5e-5)
        color_correction_max_steps = args.get('color_correction_max_steps', cfg.train.iterations)
        if self.config.use_mlp:
            params = [
                {'params': list(self.affine_trans.parameters()), 'lr': color_correction_lr_init, 'name': 'affine_trans'},
                {'params': list(self.affine_trans_sky.parameters()), 'lr': color_correction_lr_init, 'name': 'affine_trans_sky'},
            ]
        else:
            params = [
                {'params': [self.affine_trans], 'lr': color_correction_lr_init, 'name': 'affine_trans'},
                {'params': [self.affine_trans_sky], 'lr': color_correction_lr_init, 'name': 'affine_trans_sky'},
            ]
        self.optimizer = torch.optim.Adam(params=params, lr=0, eps=1e-15)

        self.color_correction_scheduler_args = get_expon_lr_func(
            lr_init=color_correction_lr_init,
            lr_final=color_correction_lr_final,
            max_steps=color_correction_max_steps,
        )

    def update_learning_rate(self, iteration):
        for param_group in self.optimizer.param_groups:
            lr = self.color_correction_scheduler_args(iteration)
            param_group['lr'] = lr
    
    def update_optimizer(self):
        self.optimizer.step()       
        self.optimizer.zero_grad(set_to_none=None)
        
    def get_id(self, camera: Camera):
        if self.mode == 'image':
            return camera.id
        elif self.mode == 'sensor':
            return camera.meta['cam']
        else:
            raise ValueError(f'invalid mode: {self.mode}')
        
    def get_affine_trans(self, camera: Camera, use_sky=False):
        if self.config.use_mlp:
            c2w = camera.ego_pose @ camera.extrinsic
            c2w = matrix_to_axis_angle(c2w.unsqueeze(0)).squeeze(0)
            if use_sky:
                affine_trans = self.affine_trans_sky(c2w).view(3, 4) + self.identity_matrix
            else:
                affine_trans = self.affine_trans(c2w).view(3, 4) + self.identity_matrix
            
        else:
            id = self.get_id(camera)
            if use_sky:
                affine_trans = self.affine_trans_sky[id]
            else:
                affine_trans = self.affine_trans[id]
                        
        self.cur_affine_trans = affine_trans
            
        return affine_trans
                
    def forward(self, camera: Camera, image: torch.Tensor, use_sky=False):
        affine_trans = self.get_affine_trans(camera, use_sky)
        image = torch.einsum('ij, jhw -> ihw', affine_trans[:3, :3], image) + affine_trans[:3, 3].unsqueeze(-1).unsqueeze(-1)
        return image

    def regularization_loss(self, camera: Camera):
        affine_trans = self.get_affine_trans(camera, use_sky=False)
        affine_trans_sky = self.get_affine_trans(camera, use_sky=True)
        
        loss = torch.abs(affine_trans - self.identity_matrix) + torch.abs(affine_trans_sky - self.identity_matrix)
        loss = loss.mean()
        return loss


class ColorCorrectionPixelAware(nn.Module):
    def __init__(self, metadata):
        super().__init__()

        self.coord_stack = dict()

        input_ch = 6 + 2  # 6(c2w) + 2(uv坐标)
        dim = 64
        self.affine_trans = nn.Sequential(
            nn.Linear(input_ch, dim),
            nn.ReLU(),
            nn.Linear(dim, dim),
            nn.ReLU(),
            nn.Linear(dim, dim),
            nn.ReLU(),
            nn.Linear(dim, 12)  # 输出3x4矩阵参数
        )
        # 初始化最后一层接近单位矩阵
        self.affine_trans[-1].weight.data.normal_(0, 1e-5)
        self.affine_trans[-1].bias.data = torch.tensor(
            [1,0,0,0, 0,1,0,0, 0,0,1,0], dtype=torch.float
        )
        self.affine_trans.cuda()

    def save_state_dict(self, is_final):
        state_dict = dict()
        state_dict['params'] = self.state_dict()
        if not is_final:
            state_dict['optimizer'] = self.optimizer.state_dict()
        return state_dict
        
    def load_state_dict(self, state_dict):
        super().load_state_dict(state_dict['params'])
        if cfg.mode == 'train' and 'optimizer' in state_dict:
            self.optimizer.load_state_dict(state_dict['optimizer'])

    def training_setup(self):
        args = cfg.optim
        color_correction_lr_init = args.get('color_correction_lr_init', 5e-4)
        color_correction_lr_final = args.get('color_correction_lr_final', 5e-5)
        color_correction_max_steps = args.get('color_correction_max_steps', cfg.train.iterations)
        params = [
            {'params': list(self.affine_trans.parameters()), 'lr': color_correction_lr_init, 'name': 'affine_trans'},
        ]
        self.optimizer = torch.optim.Adam(params=params, lr=0, eps=1e-15)

        self.color_correction_scheduler_args = get_expon_lr_func(
            lr_init=color_correction_lr_init,
            lr_final=color_correction_lr_final,
            max_steps=color_correction_max_steps,
        )

    def update_learning_rate(self, iteration):
        for param_group in self.optimizer.param_groups:
            lr = self.color_correction_scheduler_args(iteration)
            param_group['lr'] = lr
    
    def update_optimizer(self):
        self.optimizer.step()       
        self.optimizer.zero_grad(set_to_none=None)
        
    def get_affine_trans(self, camera: Camera, use_sky=False):
        cam_name = camera.meta['cam']
        C, H, W = 3, camera.image_height, camera.image_width  # [3, H, W]
        if cam_name not in self.coord_stack:
            # 生成归一化坐标网格 [-1, 1]
            u = (torch.arange(W) / (W-1)) * 2 - 1  # [W]
            v = (torch.arange(H) / (H-1)) * 2 - 1  # [H]
            coord_u, coord_v = torch.meshgrid(u, v, indexing='xy')                      # [H, W]
            # # [2, H, W]               
            coord_stack = torch.stack([coord_u, coord_v]).to(camera.ego_pose.device)    
            self.coord_stack[cam_name] = coord_stack
        else:
            coord_stack = self.coord_stack[cam_name]
        
        c2w = camera.ego_pose @ camera.extrinsic
        c2w = matrix_to_axis_angle(c2w.unsqueeze(0)).squeeze(0)
        c2w_broadcast = c2w.view(6,1,1).expand(6, H, W) 
        mlp_input = torch.cat([c2w_broadcast, coord_stack], dim=0)  # [6+2=8, H, W]
        
        # 转换为MLP输入格式 [H*W, 8]
        mlp_input = mlp_input.permute(1,2,0).reshape(-1, 8)         # [H*W, 8]
        
        # 生成位置相关仿射参数
        affine_params = self.affine_trans(mlp_input)                # [H*W, 12]
        affine_matrix = affine_params.view(H, W, 3, 4)              # [H, W, 3, 4]
        return affine_matrix

    def forward(self, camera: Camera, image: torch.Tensor, use_sky=False):
        affine_matrix = self.get_affine_trans(camera, use_sky)
        # 应用校正
        corrected = torch.einsum('hwrc,chw->rhw', 
                            affine_matrix[..., :3], image) + affine_matrix[..., 3].permute(2, 0, 1)
        return corrected

    def smoothness_loss(self, affine_matrix):
        # 计算水平/垂直方向梯度
        dx = affine_matrix[:, 1:] - affine_matrix[:, :-1]  # 水平梯度 [H,W-1,3,4]
        dy = affine_matrix[1:, :] - affine_matrix[:-1, :]  # 垂直梯度 [H-1,W,3,4]
        
        # 二阶导约束 (曲率平滑)
        dxx = dx[:, 1:] - dx[:, :-1]                     # [H,W-2,3,4]
        dyy = dy[1:, :] - dy[:-1, :]                     # [H-2,W,3,4]
        
        return 0.5*(dx.abs().mean() + dy.abs().mean()) + 0.3*(dxx.abs().mean() + dyy.abs().mean())

    def regularization_loss(self, camera: Camera):
        affine_matrix = self.get_affine_trans(camera)
        # 基础行列式约束
        det_loss = torch.abs(torch.det(affine_matrix[..., :3]) - 1.0)
        # 宽松的单位矩阵约束（仅约束对角线）
        diag_loss = torch.abs(affine_matrix[..., 0,0] - 1.0) + \
                    torch.abs(affine_matrix[..., 1,1] - 1.0) + \
                    torch.abs(affine_matrix[..., 2,2] - 1.0)
        # smoothness loss
        smoothness_loss = self.smoothness_loss(affine_matrix)
        return 0.7 * det_loss.mean() + 0.3 * diag_loss.mean() + smoothness_loss
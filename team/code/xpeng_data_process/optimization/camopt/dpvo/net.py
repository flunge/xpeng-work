import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F
from collections import OrderedDict

import torch_scatter
from torch_scatter import scatter_sum

from . import fastba
from . import altcorr
from . import lietorch
from .lietorch import SE3

from .extractor import BasicEncoder, BasicEncoder4
from .blocks import GradientClip, GatedResidual, SoftAgg

from .utils import *
from .ba import BA
from . import projective_ops as pops

autocast = torch.cuda.amp.autocast
import matplotlib.pyplot as plt

DIM = 384

class Update(nn.Module):
    def __init__(self, p):
        super(Update, self).__init__()

        self.c1 = nn.Sequential(
            nn.Linear(DIM, DIM),
            nn.ReLU(inplace=True),
            nn.Linear(DIM, DIM))

        self.c2 = nn.Sequential(
            nn.Linear(DIM, DIM),
            nn.ReLU(inplace=True),
            nn.Linear(DIM, DIM))
        
        self.norm = nn.LayerNorm(DIM, eps=1e-3)

        self.agg_kk = SoftAgg(DIM)
        self.agg_ij = SoftAgg(DIM)

        self.gru = nn.Sequential(
            nn.LayerNorm(DIM, eps=1e-3),
            GatedResidual(DIM),
            nn.LayerNorm(DIM, eps=1e-3),
            GatedResidual(DIM),
        )

        self.corr = nn.Sequential(
            nn.Linear(2*49*p*p, DIM),
            nn.ReLU(inplace=True),
            nn.Linear(DIM, DIM),
            nn.LayerNorm(DIM, eps=1e-3),
            nn.ReLU(inplace=True),
            nn.Linear(DIM, DIM),
        )

        self.d = nn.Sequential(
            nn.ReLU(inplace=False),
            nn.Linear(DIM, 2),
            GradientClip())

        self.w = nn.Sequential(
            nn.ReLU(inplace=False),
            nn.Linear(DIM, 2),
            GradientClip(),
            nn.Sigmoid())


    def forward(self, net, inp, corr, flow, ii, jj, kk):
        """ update operator """

        net = net + inp + self.corr(corr)
        net = self.norm(net)

        ix, jx = fastba.neighbors(kk, jj)
        mask_ix = (ix >= 0).float().reshape(1, -1, 1)
        mask_jx = (jx >= 0).float().reshape(1, -1, 1)

        net = net + self.c1(mask_ix * net[:,ix])
        net = net + self.c2(mask_jx * net[:,jx])

        net = net + self.agg_kk(net, kk)
        net = net + self.agg_ij(net, ii*12345 + jj)

        net = self.gru(net)

        return net, (self.d(net), self.w(net), None)


class Patchifier(nn.Module):
    def __init__(self, patch_size=3):
        super(Patchifier, self).__init__()
        self.patch_size = patch_size
        self.fnet = BasicEncoder4(output_dim=128, norm_fn='instance')
        self.inet = BasicEncoder4(output_dim=DIM, norm_fn='none')

    def __image_gradient(self, images):
        gray = ((images + 0.5) * (255.0 / 2)).sum(dim=2)
        dx = gray[...,:-1,1:] - gray[...,:-1,:-1]
        dy = gray[...,1:,:-1] - gray[...,:-1,:-1]
        g = torch.sqrt(dx**2 + dy**2)
        g = F.avg_pool2d(g, 4, 4)
        return g

    def __prepare_mask(self, mask, n, h, w, device):
        """
        将输入的 mask（通常为原图分辨率 H x W）转换到 patch 特征图分辨率 [n, h, w]。
        如果无法安全对齐分辨率，则返回 None（等价于不使用 mask）。
        """
        if mask is None:
            return None

        if not torch.is_tensor(mask):
            mask = torch.as_tensor(mask, device=device)
        else:
            mask = mask.to(device)

        # 转成 float 方便做池化
        if mask.dtype == torch.bool:
            mask_f = mask.float()
        elif mask.dtype.is_floating_point:
            mask_f = mask
        else:
            mask_f = mask.float()

        Hm, Wm = mask_f.shape[-2], mask_f.shape[-1]

        # 如果已经是特征分辨率，直接用
        if Hm == h and Wm == w:
            m_feat = mask_f
        else:
            # 否则尝试按整数尺度下采样到 [h, w]
            sy = Hm // h
            sx = Wm // w
            if sy <= 0 or sx <= 0 or Hm % h != 0 or Wm % w != 0:
                # 分辨率无法对齐，放弃使用 mask，避免采样出错
                return None

            m = mask_f.view(1, 1, Hm, Wm)
            # 使用 max-pool，下采样后只要有一个像素为 True，就认为该格有效
            m_feat = F.max_pool2d(m, kernel_size=(sy, sx), stride=(sy, sx))[0, 0]

        # 现在 m_feat 的末两维是 [h, w]，扩展到 [n, h, w]
        if m_feat.dim() == 2:
            m_feat = m_feat.unsqueeze(0)  # [1, h, w]

        if m_feat.shape[0] == 1 and n > 1:
            m_feat = m_feat.repeat(n, 1, 1)
        elif m_feat.shape[0] != n:
            # 形状不一致时，简单截断/保留前 n 帧，避免维度错误
            m_feat = m_feat[:n]

        return (m_feat > 0.5)

    def __sample_coords(self, n, h, w, num_per_image, device, mask=None):
        """
        从 [1, w-1) x [1, h-1) 上随机采样坐标。
        如果提供了 mask（[n, h, w] 且为 True 的地方才允许落点），则只在 mask 为 True 的位置采样；
        若某一帧的 mask 全 False，则退化为全图随机。
        """
        if mask is None:
            x = torch.randint(1, w - 1, size=[n, num_per_image], device=device)
            y = torch.randint(1, h - 1, size=[n, num_per_image], device=device)
            return x, y

        m = mask.clone()
        # 保持与原代码一致，不在边界采样
        m[:, 0, :] = False
        m[:, -1, :] = False
        m[:, :, 0] = False
        m[:, :, -1] = False

        xs_all = []
        ys_all = []

        for i in range(n):
            ys, xs = torch.where(m[i])

            if xs.numel() == 0:
                # 当前帧没有合法位置，退化为全图随机
                x_i = torch.randint(1, w - 1, size=[num_per_image], device=device)
                y_i = torch.randint(1, h - 1, size=[num_per_image], device=device)
            else:
                idx = torch.randint(0, xs.numel(), size=[num_per_image], device=device)
                x_i = xs[idx]
                y_i = ys[idx]

            xs_all.append(x_i)
            ys_all.append(y_i)

        x = torch.stack(xs_all, dim=0)
        y = torch.stack(ys_all, dim=0)
        return x, y

    def forward(self, images, patches_per_image=80, disps=None, centroid_sel_strat='RANDOM', return_color=False, mask=None):
        """ extract patches from input images """
        fmap = self.fnet(images) / 4.0
        imap = self.inet(images) / 4.0

        b, n, c, h, w = fmap.shape
        P = self.patch_size

        # 根据传入的 mask，准备好与特征图对齐的 mask_feat（形状 [n, h, w]）
        mask_feat = self.__prepare_mask(mask, n, h, w, fmap.device)

        # bias patch selection towards regions with high gradient
        if centroid_sel_strat == 'GRADIENT_BIAS':
            g = self.__image_gradient(images)
            # 在 mask 为 True 的区域内采样候选点（若 mask 为 None，则退化为全图随机）
            x, y = self.__sample_coords(n, h, w, 3 * patches_per_image, fmap.device, mask_feat)

            coords = torch.stack([x, y], dim=-1).float()
            g = altcorr.patchify(g[0,:,None], coords, 0).view(n, 3 * patches_per_image)
            
            ix = torch.argsort(g, dim=1)
            x = torch.gather(x, 1, ix[:, -patches_per_image:])
            y = torch.gather(y, 1, ix[:, -patches_per_image:])

        elif centroid_sel_strat == 'RANDOM':
            # 纯随机采样，同样限制在 mask 为 True 的区域内（若提供了 mask）
            x, y = self.__sample_coords(n, h, w, patches_per_image, fmap.device, mask_feat)

        else:
            raise NotImplementedError(f"Patch centroid selection not implemented: {centroid_sel_strat}")

        coords = torch.stack([x, y], dim=-1).float()
        imap = altcorr.patchify(imap[0], coords, 0).view(b, -1, DIM, 1, 1)
        gmap = altcorr.patchify(fmap[0], coords, P//2).view(b, -1, 128, P, P)

        if return_color:
            clr = altcorr.patchify(images[0], 4*(coords + 0.5), 0).view(b, -1, 3)

        if disps is None:
            disps = torch.ones(b, n, h, w, device="cuda")

        grid, _ = coords_grid_with_index(disps, device=fmap.device)
        patches = altcorr.patchify(grid[0], coords, P//2).view(b, -1, 3, P, P)

        index = torch.arange(n, device="cuda").view(n, 1)
        index = index.repeat(1, patches_per_image).reshape(-1)

        if return_color:
            return fmap, gmap, imap, patches, index, clr

        return fmap, gmap, imap, patches, index


class CorrBlock:
    def __init__(self, fmap, gmap, radius=3, dropout=0.2, levels=[1,4]):
        self.dropout = dropout
        self.radius = radius
        self.levels = levels

        self.gmap = gmap
        self.pyramid = pyramidify(fmap, lvls=levels)

    def __call__(self, ii, jj, coords):
        corrs = []
        for i in range(len(self.levels)):
            corrs += [ altcorr.corr(self.gmap, self.pyramid[i], coords / self.levels[i], ii, jj, self.radius, self.dropout) ]
        return torch.stack(corrs, -1).view(1, len(ii), -1)


class VONet(nn.Module):
    def __init__(self, use_viewer=False):
        super(VONet, self).__init__()
        self.P = 3
        self.patchify = Patchifier(self.P)
        self.update = Update(self.P)

        self.DIM = DIM
        self.RES = 4


    # @autocast(enabled=False)
    def forward(self, images, poses, disps, intrinsics, M=1024, STEPS=12, P=1, structure_only=False, rescale=False):
        """ Estimates SE3 or Sim3 between pair of frames """

        images = 2 * (images / 255.0) - 0.5
        intrinsics = intrinsics / 4.0
        disps = disps[:, :, 1::4, 1::4].float()

        fmap, gmap, imap, patches, ix = self.patchify(images, disps=disps)

        corr_fn = CorrBlock(fmap, gmap)

        b, N, c, h, w = fmap.shape
        p = self.P

        patches_gt = patches.clone()
        Ps = poses

        d = patches[..., 2, p//2, p//2]
        patches = set_depth(patches, torch.rand_like(d))

        kk, jj = flatmeshgrid(torch.where(ix < 8)[0], torch.arange(0,8, device="cuda"), indexing='ij')
        ii = ix[kk]

        imap = imap.view(b, -1, DIM)
        net = torch.zeros(b, len(kk), DIM, device="cuda", dtype=torch.float)
        
        Gs = SE3.IdentityLike(poses)

        if structure_only:
            Gs.data[:] = poses.data[:]

        traj = []
        bounds = [-64, -64, w + 64, h + 64]
        
        while len(traj) < STEPS:
            Gs = Gs.detach()
            patches = patches.detach()

            n = ii.max() + 1
            if len(traj) >= 8 and n < images.shape[1]:
                if not structure_only: Gs.data[:,n] = Gs.data[:,n-1]
                kk1, jj1 = flatmeshgrid(torch.where(ix  < n)[0], torch.arange(n, n+1, device="cuda"), indexing='ij')
                kk2, jj2 = flatmeshgrid(torch.where(ix == n)[0], torch.arange(0, n+1, device="cuda"), indexing='ij')

                ii = torch.cat([ix[kk1], ix[kk2], ii])
                jj = torch.cat([jj1, jj2, jj])
                kk = torch.cat([kk1, kk2, kk])

                net1 = torch.zeros(b, len(kk1) + len(kk2), DIM, device="cuda")
                net = torch.cat([net1, net], dim=1)

                if np.random.rand() < 0.1:
                    k = (ii != (n - 4)) & (jj != (n - 4))
                    ii = ii[k]
                    jj = jj[k]
                    kk = kk[k]
                    net = net[:,k]

                patches[:,ix==n,2] = torch.median(patches[:,(ix == n-1) | (ix == n-2),2])
                n = ii.max() + 1

            coords = pops.transform(Gs, patches, intrinsics, ii, jj, kk)
            coords1 = coords.permute(0, 1, 4, 2, 3).contiguous()

            corr = corr_fn(kk, jj, coords1)
            net, (delta, weight, _) = self.update(net, imap[:,kk], corr, None, ii, jj, kk)

            lmbda = 1e-4
            target = coords[...,p//2,p//2,:] + delta

            ep = 10
            for itr in range(2):
                Gs, patches = BA(Gs, patches, intrinsics, target, weight, lmbda, ii, jj, kk, 
                    bounds, ep=ep, fixedp=1, structure_only=structure_only)

            kl = torch.as_tensor(0)
            dij = (ii - jj).abs()
            k = (dij > 0) & (dij <= 2)

            coords = pops.transform(Gs, patches, intrinsics, ii[k], jj[k], kk[k])
            coords_gt, valid, _ = pops.transform(Ps, patches_gt, intrinsics, ii[k], jj[k], kk[k], jacobian=True)

            traj.append((valid, coords, coords_gt, Gs[:,:n], Ps[:,:n], kl))

        return traj


"""
DifixCarmaskAwareRenderStrategy
================================

与 DifixRenderStrategy 的区别:
    DifixRenderStrategy 的流程:
        高斯渲染 -> redistort_gpu (此步骤已把真实车身贴入) -> difix (会"修复"车身) -> resize

    本 strategy 的流程 (按用户需求):
        1) 高斯渲染
        2) redistort_gpu_without_mask  -> 仅做畸变, 不贴车身
        3) difix 修复 (带 ref + 车身 mask, mask 区域 = 1.0 表示让 difix 忽略 ref 的车身区域)
        4) 把真实车身贴回 difix 输出

这样 difix 不会再"修复"车身像素, 也避免 ref 车身贴片对 difix 的形状先验造成干扰.
"""

import time

import torch

from reconic.simulator.render_strategy.difix_render_strategy import DifixRenderStrategy


class DifixCarmaskAwareRenderStrategy(DifixRenderStrategy):

    # ---------------------------- helpers ----------------------------

    def _get_render_mask_origin(self, simulator, cam_name):
        return simulator.render_mask_dict_origin_tensor.get(cam_name, None)

    def _get_render_mask(self, simulator, cam_name):
        return simulator.render_mask_dict_tensor.get(cam_name, None)

    def _get_real_carbody_image_origin(self, simulator, cam_name):
        """真实车身图像 uint8 [3, H, W]; 若无则返回 None."""
        return simulator.images_real_tensor_origin.get(cam_name, None)

    def _get_real_carbody_image(self, simulator, cam_name):
        return simulator.images_real_tensor.get(cam_name, None)

    def _build_ref_mask_for_difix(self, simulator, cam_name, target_hw):
        """
        构造给 difix 的 ref_mask (float [1, H, W]):
            1.0 = ref 该位置在 attn1 中被屏蔽 (即车身区域)
            0.0 = ref 该位置正常参与
        约定与 simulator 的 render_mask 互补.
        target_hw: (H, W) 用于对齐 difix 输入尺寸.
        """
        render_mask = self._get_render_mask_origin(simulator, cam_name)
        if render_mask is None:
            return None
        ref_mask = (~render_mask).float()  # car body -> 1.0
        if target_hw is not None and tuple(ref_mask.shape) != tuple(target_hw):
            ref_mask = torch.nn.functional.interpolate(
                ref_mask.unsqueeze(0).unsqueeze(0).float(),
                size=tuple(target_hw),
                mode="nearest",
            ).squeeze(0).squeeze(0)
        return ref_mask.unsqueeze(0)  # [1, H, W]

    def _paste_carbody(self, img_tensor, simulator, cam_name):
        """
        把真实车身像素贴到 img_tensor 的车身区域.
        img_tensor: uint8 [3, H, W] (CUDA).
        """
        render_mask = self._get_render_mask(simulator, cam_name)
        img_real = self._get_real_carbody_image(simulator, cam_name)
        if render_mask is None or img_real is None:
            return img_tensor

        device = img_tensor.device
        H, W = img_tensor.shape[1], img_tensor.shape[2]

        mask = render_mask.to(device)
        if tuple(mask.shape) != (H, W):
            mask = torch.nn.functional.interpolate(
                mask.float().unsqueeze(0).unsqueeze(0),
                size=(H, W),
                mode="nearest",
            ).squeeze(0).squeeze(0).bool()

        real = img_real.to(device)
        if tuple(real.shape[1:]) != (H, W):
            real = torch.nn.functional.interpolate(
                real.float().unsqueeze(0),
                size=(H, W),
                mode="bilinear",
                align_corners=False,
            ).squeeze(0).clamp(0, 255).to(torch.uint8)

        mask_3c = mask.expand_as(img_tensor)
        out = img_tensor.clone()
        out[~mask_3c] = real[~mask_3c]
        return out

    # ----------------------------- API -----------------------------

    def render(self, simulator, camera, rendered_timestamp, ego_pose_world,
               collision_info_arr, real_car_image=None):
        print(f"[RenderStrategy] Using DifixCarmaskAwareRenderStrategy")
        t1 = time.time()
        result, camera_name = simulator.render(
            camera, int(rendered_timestamp), ego_pose_world, collision_info_arr
        )
        if result is None:
            return None
        print(f"render cost {time.time() - t1}")

        # 1) 高斯结果 -> uint8 CHW
        rgb = self._process_gs_result(result, camera_name)
        # 2) 只做畸变, 不贴车身
        img_distort_tensor = simulator.redistort_gpu_without_mask(camera_name, rgb)
        del result

        # 3) difix 修复, 带 ref + 车身 mask (mask 区域让 difix 忽略 ref)
        t2 = time.time()
        ref_image = self._get_ref_image(real_car_image, rendered_timestamp, camera)
        ref_mask = self._build_ref_mask_for_difix(
            simulator, camera_name, target_hw=img_distort_tensor.shape[1:]
        )
        img_distort_tensor = simulator.image_fixer.fix_image_xpeng(
            img_distort_tensor,
            ref_img=ref_image,
            ref_mask=ref_mask,
            camera_name=camera_name,
        )
        print(f"fix_image cost {time.time() - t2}")

        # 4) 把真实车身贴回 difix 输出
        t3 = time.time()
        img_distort_tensor = self._paste_carbody(img_distort_tensor, simulator, camera_name)
        print(f"paste carbody cost {time.time() - t3}")

        t4 = time.time()
        img_distort = self._post_process(img_distort_tensor, camera, simulator)
        print(f"post_process cost {time.time() - t4}")
        return img_distort

    def render_batch(self, simulator, camera_list, rendered_timestamp, ego_pose_world,
                     collision_info_arr, real_car_image_map=None):
        print(f"[RenderStrategy] Using DifixCarmaskAwareRenderStrategy (batch)")
        results = dict()
        gs_results = simulator.render_multi_cam(camera_list, rendered_timestamp, ego_pose_world)

        for cam_name, result in zip(camera_list, gs_results):
            rgb = self._process_gs_result(result, cam_name)
            # 2) 畸变 (不贴车身)
            img_distort_tensor = simulator.redistort_gpu_without_mask(cam_name, rgb)

            # 3) difix + ref + 车身 mask
            real_car_image = real_car_image_map.get(cam_name) if real_car_image_map else None
            ref_image = self._get_ref_image(real_car_image, rendered_timestamp, cam_name)
            ref_mask = self._build_ref_mask_for_difix(
                simulator, cam_name, target_hw=img_distort_tensor.shape[1:]
            )
            img_distort_tensor = simulator.image_fixer.fix_image_xpeng(
                img_distort_tensor,
                ref_img=ref_image,
                ref_mask=ref_mask,
                camera_name=cam_name,
            )

            # 4) 贴回真实车身
            img_distort_tensor = self._paste_carbody(img_distort_tensor, simulator, cam_name)

            img_distort = self._post_process(img_distort_tensor, cam_name, simulator)
            results[cam_name] = img_distort
            print(f"[DifixCarmaskAwareRenderStrategy] Rendering {cam_name} images done", flush=True)

        return results
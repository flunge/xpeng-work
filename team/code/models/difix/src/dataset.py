import json
import random
import torch
import os
import cv2
import numpy as np
from PIL import Image
import torchvision.transforms.functional as F
from collections import defaultdict

from ref_perturb import perturb_pil_ref


MASK_FOLDER_MAPPING = {
    50: "xpeng_data_process/assets/Vehicle_Mask/F30_Masks",
    43: "xpeng_data_process/assets/Vehicle_Mask/E38A_Masks",
    21: "xpeng_data_process/assets/Vehicle_Mask/E28A_Masks",
    40: "xpeng_data_process/assets/Vehicle_Mask/E38_Masks",
    60: "xpeng_data_process/assets/Vehicle_Mask/H93_Masks",
    70: "xpeng_data_process/assets/Vehicle_Mask/F57_Masks",
    201: "xpeng_data_process/assets/Vehicle_Mask/XP5_201_Masks",
    205: "xpeng_data_process/assets/Vehicle_Mask/XP5_269_Masks",
    203: "xpeng_data_process/assets/Vehicle_Mask/E38B_Masks",
    206: "xpeng_data_process/assets/Vehicle_Mask/F30B_Masks",
    231: "xpeng_data_process/assets/Vehicle_Mask/H93AS_Masks",
    269: "xpeng_data_process/assets/Vehicle_Mask/XP5_269_Masks",
}


def get_cam_name_from_img_id(data, img_id):
    """从 data[img_id] 的 target_image 路径提取 cam_name。"""
    output_img_path = data[img_id]["target_image"]
    return output_img_path.split("/")[-2]


class CamGroupedBatchSampler(torch.utils.data.Sampler):
    """
    保证同一 batch 内的样本都来自同一个 cam_name。
    每个 epoch 会打乱 cam 的顺序以及每个 cam 内部的样本顺序。
    """
    def __init__(self, dataset, batch_size, drop_last=False, seed=42):
        self.dataset = dataset
        self.batch_size = batch_size
        self.drop_last = drop_last
        self.seed = seed
        self.epoch = 0
        # 按 cam_name 分组 indices
        self.cam_to_indices = defaultdict(list)
        for idx in range(len(dataset)):
            img_id = dataset.img_ids[idx]
            cam_name = get_cam_name_from_img_id(dataset.data, img_id)
            self.cam_to_indices[cam_name].append(idx)
        self._all_batches = []
        self._cursor = 0
        self._rebuild_batches()

    def set_epoch(self, epoch):
        self.epoch = int(epoch)
        self._rebuild_batches()
        if len(self._all_batches) > 0:
            # Shift start point per epoch so truncated epochs do not always take the same prefix.
            self._cursor = (self.epoch * 9973) % len(self._all_batches)

    def _rebuild_batches(self):
        # 先为每个 cam 生成 batch 列表，再打乱所有 batch 的顺序，使不同 step 能遇到不同 cam
        rng = random.Random(self.seed + self.epoch)
        all_batches = []
        for _, indices in self.cam_to_indices.items():
            shuffled = indices.copy()
            rng.shuffle(shuffled)
            for i in range(0, len(shuffled), self.batch_size):
                batch = shuffled[i:i + self.batch_size]
                if len(batch) == self.batch_size or not self.drop_last:
                    all_batches.append(batch)
        rng.shuffle(all_batches)
        self._all_batches = all_batches
        self._cursor = 0

    def __iter__(self):
        # Finite iterator: one logical epoch yields exactly len(self) batches.
        # Stateful cursor avoids always consuming the same prefix when training loop truncates steps.
        total = len(self._all_batches)
        if total == 0:
            return
        for _ in range(total):
            idx = self._cursor % total
            yield self._all_batches[idx]
            self._cursor = (self._cursor + 1) % total

    def __len__(self):
        total = 0
        for indices in self.cam_to_indices.values():
            n = len(indices)
            if self.drop_last:
                total += n // self.batch_size
            else:
                total += (n + self.batch_size - 1) // self.batch_size
        return total


class PairedDataset(torch.utils.data.Dataset):
    def __init__(
        self,
        dataset_path,
        split,
        height=576,
        width=1024,
        tokenizer=None,
        enable_dual_resolution_bucket=False,
        bucket_16_9_height=576,
        bucket_16_9_width=1024,
        bucket_5_4_height=768,
        bucket_5_4_width=960,
        use_ref_img=False,
        overwrite_prompt=None,
        ref_perturb_prob=0.0,
        ref_perturb_amp=10.0,
        ref_perturb_repr_depth=15.0,
        use_ref_mask=False,
    ):
        super().__init__()
        with open(dataset_path, "r") as f:
            self.data = json.load(f)[split]
        self.img_ids = list(self.data.keys())
        self.image_size = (height, width)
        self.enable_dual_resolution_bucket = enable_dual_resolution_bucket
        self.bucket_16_9_size = (bucket_16_9_height, bucket_16_9_width)
        self.bucket_5_4_size = (bucket_5_4_height, bucket_5_4_width)
        self.use_ref_img = use_ref_img
        self.overwrite_prompt = overwrite_prompt
        self.tokenizer = tokenizer
        # ref 几何扰动 (反对齐增广); prob > 0 时生效, 仅作用于 use_ref_img=True 的样本
        self.ref_perturb_prob = float(ref_perturb_prob or 0.0)
        self.ref_perturb_amp = float(ref_perturb_amp)
        self.ref_perturb_repr_depth = float(ref_perturb_repr_depth)
        # ref 局部屏蔽 mask; 仅当 use_ref_img=True 同时 use_ref_mask=True 才读取 ref_mask 字段
        # mask 像素 >127 = 该位置 ref 应被 attn1 屏蔽; 不存在则输出全 0 mask
        self.use_ref_mask = bool(use_ref_mask)
        self.cam_names = ('cam0', 'cam2', 'cam3', 'cam4', 'cam5', 'cam6', 'cam7')
        self.code_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        # 车型级缓存：key=vehicle_model, value={cam_name: mask}
        self.vehicle_mask_cache = {}
        # clip -> vehicle_model（int 或 None）
        self.clip_vehicle_model_cache = {}

    def _select_image_size(self, origin_input_width, origin_input_height):
        if origin_input_height <= 0:
            return self.image_size[1], self.image_size[0]
        if self.enable_dual_resolution_bucket:
            aspect = origin_input_width / origin_input_height
            aspect_16_9 = 16.0 / 9.0
            aspect_5_4 = 5.0 / 4.0
            if abs(aspect - aspect_16_9) <= abs(aspect - aspect_5_4):
                return self.bucket_16_9_size[1], self.bucket_16_9_size[0]
            return self.bucket_5_4_size[1], self.bucket_5_4_size[0]
        if self.image_size[0] == 0 and self.image_size[1] == 0:
            return (
                origin_input_width - origin_input_width % 8,
                origin_input_height - origin_input_height % 8,
            )
        return self.image_size[1], self.image_size[0]

    def _resolve_vehicle_model(self, img_id, clip_id):
        if clip_id in self.clip_vehicle_model_cache:
            return self.clip_vehicle_model_cache[clip_id]

        input_img_path = self.data[img_id]["image"]
        src_img_path = "/".join(input_img_path.split("/")[:-4])
        metadata_path = os.path.join(src_img_path, "metadata.json")

        vehicle_model = None
        if os.path.exists(metadata_path):
            try:
                with open(metadata_path, "r") as f:
                    metadata = json.load(f)
                vehicle_model = metadata.get("vehicle_model", None)
            except Exception as e:
                print(f"Failed to read metadata: {metadata_path}, error: {e}")
        else:
            print(f"Metadata file not found: {metadata_path}")

        self.clip_vehicle_model_cache[clip_id] = vehicle_model
        return vehicle_model

    def _build_vehicle_masks(self, vehicle_model, target_height, target_width):
        cache_key = (vehicle_model, target_height, target_width)
        if cache_key in self.vehicle_mask_cache:
            return self.vehicle_mask_cache[cache_key]

        mask_dict = {}
        mask_folder = MASK_FOLDER_MAPPING.get(vehicle_model, None)
        if mask_folder is not None:
            mask_folder = f"{mask_folder}_Origin"

        for cam_name in self.cam_names:
            mask = None
            if mask_folder is not None:
                mask_file_name = f"_{cam_name}_mask.png"
                mask_path = os.path.join(self.code_dir, mask_folder, mask_file_name)
                if os.path.exists(mask_path):
                    mask = cv2.imread(mask_path, cv2.IMREAD_GRAYSCALE)
                    if target_height > 0 and target_width > 0:
                        mask = cv2.resize(
                            mask,
                            (target_width, target_height),
                            interpolation=cv2.INTER_NEAREST
                        )
                else:
                    # print(f"Mask file not found: {mask_path}, Use all white mask")
                    if target_height > 0 and target_width > 0:
                        mask = np.ones((target_height, target_width), dtype=np.uint8) * 255
                    else:
                        mask = None
            if mask is not None:
                mask = np.expand_dims(mask, axis=0)
            mask_dict[cam_name] = mask

        self.vehicle_mask_cache[cache_key] = mask_dict
        return mask_dict
            
    def __len__(self):
        return len(self.img_ids)

    def __getitem__(self, idx):
        num_samples = len(self.img_ids)
        if num_samples == 0:
            raise RuntimeError("Dataset is empty.")

        idx = int(idx) % num_samples
        last_err = None

        # 迭代重试，避免递归导致 RecursionError
        for offset in range(num_samples):
            cur_idx = (idx + offset) % num_samples
            img_id = self.img_ids[cur_idx]

            input_img_path = self.data[img_id]["image"]
            output_img_path = self.data[img_id]["target_image"]
            caption = self.overwrite_prompt if self.overwrite_prompt is not None else self.data[img_id]["prompt"]
            clip_id = self.data[img_id]["clip_id"]

            if "ref_image" in self.data[img_id] and len(self.data[img_id]["ref_image"]) > 0:
                ref_img_path = self.data[img_id]["ref_image"]
            else:
                ref_img_path = None

            ref_mask_path = None
            if self.use_ref_img and self.use_ref_mask:
                _maybe = self.data[img_id].get("ref_mask", None)
                if isinstance(_maybe, str) and len(_maybe) > 0:
                    ref_mask_path = _maybe

            ref_mask_pil = None
            try:
                input_img = Image.open(input_img_path)
                output_img = Image.open(output_img_path)
                origin_input_width, origin_input_height = input_img.size
                img_t = F.to_tensor(input_img)
                output_t = F.to_tensor(output_img)
                if self.use_ref_img and ref_img_path is not None:
                    ref_img = Image.open(ref_img_path)
                    # ref 几何扰动: 仅当 prob>0 触发, 且该样本未被标注为 augmented
                    augmented_flag = bool(self.data[img_id].get("augmented", False))
                    if (
                        self.ref_perturb_prob > 0
                        and not augmented_flag
                        and random.random() < self.ref_perturb_prob
                    ):
                        cam_name_for_perturb = output_img_path.split("/")[-2]
                        try:
                            ref_img = perturb_pil_ref(
                                ref_img,
                                cam_name_for_perturb,
                                amp=self.ref_perturb_amp,
                                repr_depth=self.ref_perturb_repr_depth,
                            )
                        except Exception as perturb_err:
                            print(
                                f"[ref_perturb] failed on {ref_img_path} "
                                f"({cam_name_for_perturb}): {perturb_err}"
                            )
                    ref_t = F.to_tensor(ref_img)
                if self.use_ref_img and self.use_ref_mask and ref_mask_path is not None:
                    try:
                        ref_mask_pil = Image.open(ref_mask_path).convert("L")
                    except Exception as mask_err:
                        print(
                            f"Error loading ref_mask {ref_mask_path}: {mask_err}; "
                            "fallback to empty mask."
                        )
                        ref_mask_pil = None
                break
            except Exception as e:
                last_err = e
                print(f"Error loading image pair, skip sample idx={cur_idx}: {input_img_path}, {output_img_path}; err={e}")
        else:
            raise RuntimeError(
                f"Failed to load any valid sample after trying {num_samples} items; last_err={last_err}"
            )

        new_width, new_height = self._select_image_size(origin_input_width, origin_input_height)
            
        img_t = F.resize(img_t, (new_height, new_width))
        img_t = F.normalize(img_t, mean=[0.5], std=[0.5])

        output_t = F.resize(output_t, (new_height, new_width))
        output_t = F.normalize(output_t, mean=[0.5], std=[0.5])

        # 仅当 use_ref_img 时才加 ref_t；无 ref 路径时用 output_t 作为 ref_t
        if self.use_ref_img:
            if ref_img_path is not None:
                ref_t = F.resize(ref_t, (new_height, new_width))
                ref_t = F.normalize(ref_t, mean=[0.5], std=[0.5])
                img_t = torch.stack([img_t, ref_t], dim=0)
                output_t = torch.stack([output_t, ref_t], dim=0)
            else:
                ref_t = output_t.clone()
                img_t = torch.stack([img_t, ref_t], dim=0)
                output_t = torch.stack([output_t, ref_t], dim=0)
        else:
            # 未使用 use_ref_img：不处理 ref_t，保持单 view
            img_t = img_t.unsqueeze(0)
            output_t = output_t.unsqueeze(0)

        cam_name = output_img_path.split("/")[-2]
        vehicle_model = self._resolve_vehicle_model(img_id, clip_id)
        mask_dict = self._build_vehicle_masks(vehicle_model, new_height, new_width)
        mask = mask_dict[cam_name]
        if mask is None:
            mask = np.ones((1, new_height, new_width), dtype=np.uint8) * 255
        elif mask.shape[-2:] != (new_height, new_width):
            # mask is numpy array, use cv2 to resize
            mask = cv2.resize(mask[0], (new_width, new_height), interpolation=cv2.INTER_NEAREST)
            mask = mask[np.newaxis, :, :]

        # ref_mask 输出: [1, H, W] float32, 1.0=屏蔽, 0.0=保留; 不启用时为全 0
        if self.use_ref_img and self.use_ref_mask:
            if ref_mask_pil is not None:
                ref_mask_pil_r = ref_mask_pil.resize((new_width, new_height), Image.NEAREST)
                ref_mask_arr = np.array(ref_mask_pil_r, dtype=np.uint8)
                ref_mask_t = torch.from_numpy((ref_mask_arr > 127).astype(np.float32))[None]
            else:
                ref_mask_t = torch.zeros(1, new_height, new_width, dtype=torch.float32)
        else:
            ref_mask_t = torch.zeros(1, new_height, new_width, dtype=torch.float32)

        out = {
            "output_pixel_values": output_t,
            "conditioning_pixel_values": img_t,
            "caption": caption,
            "mask": mask,
            "ref_mask": ref_mask_t,
            "cam_name": cam_name,   
            "origin_input_width": origin_input_width,
            "origin_input_height": origin_input_height
        }
        
        if self.tokenizer is not None:
            input_ids = self.tokenizer(
                caption, max_length=self.tokenizer.model_max_length,
                padding="max_length", truncation=True, return_tensors="pt"
            ).input_ids
            out["input_ids"] = input_ids

        return out

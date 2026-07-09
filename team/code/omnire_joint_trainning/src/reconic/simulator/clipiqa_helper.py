"""ClipIQAHelper: CLIP-IQA 图像质量评分辅助类，解耦自 ReconicSimulator。

使用方式（组合模式）：
    # ReconicSimulator.__init__ 中
    from .clipiqa_helper import ClipIQAHelper
    self.clipiqa = ClipIQAHelper()
    self.clipiqa.init_model()   # 可选，失败时 self.clipiqa = None

    # 渲染后评分（由 closed_loop_api 通过 simulator 薄包装调用）
    self.clipiqa.apply_to_info(info, img_rgb, camera, ts, self.model_path)

    # 保存结果
    self.clipiqa.save_scores(self.model_path)
"""

from __future__ import annotations

import json
import os
import sys
import tempfile

import cv2
import numpy as np
import torch


class ClipIQAHelper:
    """独立的 CLIP-IQA 评分辅助对象，不依赖任何 Simulator 基类。"""

    # 评测时统一 resize 到此尺寸（仅影响评分，不影响渲染输出）
    EVAL_SIZE = (512, 384)  # (width, height)

    def __init__(self) -> None:
        self._model = None
        self._attr_names: list[str] = []
        self._records: list[dict] = []

    # ---------------------------------------------------------------- 初始化

    def init_model(
        self,
        config: str = "configs/clipiqa/clipiqa_attribute_test_my.py",
        device: int = 0,
    ) -> None:
        """加载 CLIP-IQA 模型。

        config: 相对于 CLIP-IQA 根目录的路径，或绝对路径。
        """
        clipiqa_root = os.path.abspath(
            os.path.join(os.path.dirname(__file__), "..", "..", "..", "..", "models", "CLIP-IQA")
        )
        if clipiqa_root not in sys.path:
            sys.path.insert(0, clipiqa_root)
        try:
            from mmedit.apis import init_model  # noqa
            import mmcv
        except ImportError as e:
            raise ImportError(
                f"[CLIP-IQA] 无法导入 mmedit，请确认 CLIP-IQA 环境已激活。错误: {e}"
            )
        if not os.path.isabs(config):
            config = os.path.join(clipiqa_root, config)
        self._model = init_model(config, None, device=torch.device("cuda", device))
        cfg = mmcv.Config.fromfile(config)
        classnames = cfg.model.generator.get("classnames", [])
        self._attr_names = []
        for pair in classnames:
            if isinstance(pair, (list, tuple)) and len(pair) > 0:
                self._attr_names.append(pair[0].split()[0])  # 'Sharp photo.' -> 'Sharp'
        if not self._attr_names:
            self._attr_names = [f"attr{i}" for i in range(3)]
        self._records = []
        print(f"[CLIP-IQA] 初始化完成，属性: {self._attr_names}", flush=True)

    # ---------------------------------------------------------------- 评分

    def score(self, img_rgb: np.ndarray) -> dict:
        """对一张 H×W×3 uint8 RGB numpy 图像计算 CLIP-IQA 评分。

        评分前统一 resize 到 EVAL_SIZE (W×H)，不影响原始渲染结果。
        返回 {attr_name: score(0-100)} 字典；模型未初始化时返回空字典。
        """
        if self._model is None:
            return {}
        from mmedit.apis import restoration_inference

        fd, tmp_path = tempfile.mkstemp(suffix=".png")
        try:
            os.close(fd)
            eval_w, eval_h = self.EVAL_SIZE
            img_eval = cv2.resize(
                cv2.cvtColor(img_rgb, cv2.COLOR_RGB2BGR),
                (eval_w, eval_h),
                interpolation=cv2.INTER_AREA,
            )
            cv2.imwrite(tmp_path, img_eval)
            _, attributes = restoration_inference(
                self._model, tmp_path, return_attributes=True
            )
            attrs = attributes.float().detach().cpu().numpy()
            attrs = np.squeeze(attrs)
            if attrs.ndim == 0:
                attrs = attrs.reshape(1)
            return {
                name: float(attrs[i]) * 100
                for i, name in enumerate(self._attr_names)
                if i < len(attrs)
            }
        except Exception as e:
            print(f"[CLIP-IQA] 评分失败: {e}", flush=True)
            return {name: float("nan") for name in self._attr_names}
        finally:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass

    def unpack_and_score_ref(self, ref_dict) -> dict:
        """解包 real_car_image 字典（{image, height, width}，RGB flat array）并计算 CLIP-IQA 评分。

        返回 {ref_Sharp: ..., ref_Clean: ..., ref_Perfect: ...}；
        ref_dict 为 None 或模型未初始化时返回空字典（不写入 record）。
        """
        if ref_dict is None or self._model is None:
            return {}
        img_flat = ref_dict.get("image")
        h = ref_dict.get("height")
        w = ref_dict.get("width")
        if img_flat is None or h is None or w is None:
            return {}
        try:
            img_np = np.frombuffer(img_flat, dtype=np.uint8).reshape(int(h), int(w), 3)
            scores = self.score(img_np)  # img_np 已是 RGB，与 img_distort 一致
            return {f"ref_{k}": v for k, v in scores.items()}
        except Exception as e:
            print(f"[CLIP-IQA] ref image 评分失败: {e}", flush=True)
            return {}

    def apply_to_info(
        self,
        info: dict,
        img_rgb: np.ndarray,
        camera: str,
        rendered_timestamp: int,
        model_path: str,
        real_car_image=None,
    ) -> None:
        """对渲染结果计分并写入 info['clipiqa']，同时追加记录并 flush。

        real_car_image: 真实参考图字典 {image, height, width}（flat RGB uint8 bytes）；
        有值时同步计算 ref 评分并写入 info['clipiqa_ref'] 和 record。
        由 ReconicSimulator.apply_clipiqa_to_info 薄包装调用。
        """
        if self._model is None:
            return
        scores = self.score(img_rgb)
        ref_scores = self.unpack_and_score_ref(real_car_image)
        info["clipiqa"] = scores
        info["clipiqa_ref"] = ref_scores
        record = {
            "timestamp": int(rendered_timestamp),
            "camera": camera,
            **scores,       # Sharp, Clean, Perfect（渲染图）
            **ref_scores,   # ref_Sharp, ref_Clean, ref_Perfect（真实图，仅在 ref 可用时存在）
        }
        self._records.append(record)
        print(
            f"[CLIP-IQA] {camera} ts={rendered_timestamp} rendered={scores} ref={ref_scores}",
            flush=True,
        )
        self.flush_scores(model_path)

    # ---------------------------------------------------------------- 持久化

    @staticmethod
    def _get_result_dir(model_path: str) -> str:
        """根据 model_path 推算评分结果目录。

        例：model_path = /tmp/binary_1718279/104609456_dds/3dgs/model1
             → /tmp/binary_1718279/104609456_result/
        """
        dds_dir = os.path.dirname(os.path.dirname(model_path))  # .../104609456_dds
        parent = os.path.dirname(dds_dir)                        # .../binary_1718279
        dds_name = os.path.basename(dds_dir)                     # 104609456_dds
        result_name = dds_name.rsplit("_dds", 1)[0] + "_result"  # 104609456_result
        return os.path.join(parent, result_name)

    def flush_scores(self, model_path: str) -> None:
        """将当前全部记录写入 <result_dir>/clipiqa_scores.json（覆盖写）。"""
        if not self._records:
            return
        try:
            result_dir = self._get_result_dir(model_path)
            os.makedirs(result_dir, exist_ok=True)
            json_path = os.path.join(result_dir, "clipiqa_scores.json")
            with open(json_path, "w", encoding="utf-8") as f:
                json.dump(
                    {"attribute_names": self._attr_names, "records": self._records},
                    f,
                    ensure_ascii=False,
                    indent=2,
                )
            print(
                f"[CLIP-IQA] 已写入 {json_path}（共 {len(self._records)} 条）",
                flush=True,
            )
        except Exception as e:
            print(f"[CLIP-IQA] flush 写文件失败: {e}", flush=True)

    def save_scores(self, model_path: str, save_path: str = None) -> None:
        """将全部记录保存为 clipiqa_scores.json。

        save_path 为 None 时自动推算结果目录。
        """
        if not self._records:
            print("[CLIP-IQA] 暂无评分记录，跳过保存。", flush=True)
            return
        target_dir = save_path if save_path else self._get_result_dir(model_path)
        os.makedirs(target_dir, exist_ok=True)
        json_path = os.path.join(target_dir, "clipiqa_scores.json")
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(
                {"attribute_names": self._attr_names, "records": self._records},
                f,
                ensure_ascii=False,
                indent=2,
            )
        print(
            f"[CLIP-IQA] 评分结果已保存到 {json_path}（共 {len(self._records)} 条）",
            flush=True,
        )

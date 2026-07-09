#
# Created on Thu Nov 28 2024
# Author: Wenkang Qin (wkqin@outlook.com)
#
# Copyright (c) 2024 GigaAI.
#
import logging
from queue import Queue

logger = logging.getLogger()


class SerialScheduler:
    def __init__(self, max_waiting_queue_size: int = 0):
        super().__init__()
        self.training_pairs = []
        self.inference_images = []
        self.max_waiting_queue_size = max_waiting_queue_size
        self.novel_data = Queue()
        self.num_infer_samples = 0
        self.num_novel_data = 0

    def set_generative_engine(self, generative_engine):
        self.generative_engine = generative_engine
        self.training_batch_size = self.generative_engine.training_batch_size
        self.inference_batch_size = self.generative_engine.inference_batch_size

    def push_training_pairs(self, render_image, gt_image, mask, prompt: str = "remove degradation") -> bool:
        self.training_pairs.append((render_image.detach(), gt_image.detach(), mask, prompt))

        if self.generative_engine.training and len(self.training_pairs) >= self.training_batch_size:
            batch_list = self.training_pairs[: self.training_batch_size]
            batch_input_data, batch_gt, batch_mask, prompts = self.generative_engine.get_batch(batch_list)
            self.training_pairs = self.training_pairs[self.training_batch_size :]
            batch_data = batch_input_data, batch_gt, batch_mask, prompts

            self.generative_engine.training_forward(batch_data)
            return True

        return False

    def push_inference_image(
        self, image, mask, info, index, ref_image=None, prompt="Correct the rendering distortion.",
        infer_now=False
    ) -> bool:
        self.inference_images.append((image, ref_image, mask, info, index, prompt))
        self.num_infer_samples += 1

        # TODO: below code should be executed async

        infer_batch_size = 0
        if self.inference_batch_size > 1 :
            # 检查数据是否支持batch infer，主要是图像尺寸是否一致
            if len(self.inference_images) >= self.inference_batch_size :
                infer_batch_size = self.inference_batch_size
                for i in range(infer_batch_size - 1):
                    if self.inference_images[i][0].shape != self.inference_images[i+1][0].shape :
                        # 如果实际数据尺寸不一致，不支持batch infer，此次改成单帧infer
                        infer_batch_size = 1
                        break
                # 能够batch infer
            elif len(self.inference_images) > 0 and infer_now :
                # 强制单帧infer
                infer_batch_size = 1
        elif len(self.inference_images) > 0 :
            # 单帧infer模式下，能否infer
            infer_batch_size = 1

        if infer_batch_size > 0 :
            batch_list = self.inference_images[: infer_batch_size]
            batch_data, ref_data, masks, infos, index, prompts, ori_sizes = self.generative_engine.get_infer_batch(
                batch_list
            )

            batch_results = self.generative_engine.inference_forward(
                batch_data, ref_data, masks, infos, index, prompts, ori_sizes
            )

            for batch_result in batch_results:
                self.novel_data.put(batch_result)
                self.num_novel_data += 1

            self.inference_images = self.inference_images[infer_batch_size :]

            return True
        else :
            return False

    def reset_queue(self):
        self.training_pairs.clear()
        self.inference_images.clear()
        while not self.novel_data:
            self.novel_data.get()
        self.num_infer_samples = 0

    def get_novel_data(self):
        if self.num_novel_data == 0:
            return None
        degrad_data, novel_data, sky_mask, info, index = self.novel_data.get()
        self.num_novel_data -= 1
        return degrad_data, novel_data, sky_mask, info, index

    def __enter__(self):
        return self

    def __exit__(self, type, value, traceback):
        self.stop_threads()

    def set_train(self):
        self.generative_engine.set_train()

    def set_eval(self):
        self.generative_engine.set_eval()

    def save_checkpoint(self, log_dir: str, step: int, is_final: bool = False):
        self.generative_engine.save_checkpoint(log_dir, step, is_final)

    def resume_from_checkpoint(self, ckpt_path: str) -> None:
        self.generative_engine.resume_from_checkpoint(ckpt_path)

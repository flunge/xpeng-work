import os

from ..training_loop.training_loop_helper import TrainingLoopHelper
from ..utils.recorder import Recorder


class XpengTrainingLoop(TrainingLoopHelper):
    def __init__(self, args):
        super().__init__(args)
        self.recorder = Recorder(self.cfg, args)
        
    def forward_step(self, step, train_data):
        _, image_info, cam_info = train_data
        outputs = self.recon_trainer(image_info, cam_info)
        self.recon_trainer.update_visibility_filter()
        loss_dict = self.recon_trainer.compute_losses(
            outputs=outputs,
            image_info=image_info,
            cam_info=cam_info,
            from_synthesis=False,
        )
        return outputs, loss_dict

    def backward_step(self, step, ouptputs, loss_dict):
        self.recon_trainer.backward(loss_dict)

    def run_after_step_finished(self, step, train_data, outputs, loss_dict):
        self.recorder.update(step, train_data, outputs, loss_dict, self.recon_trainer)
        super().run_after_step_finished(step, train_data, outputs, loss_dict)
        
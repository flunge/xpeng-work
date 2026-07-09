import json
import logging
import os
import time
import sys
import cv2

import imageio
import numpy as np
import torch
import torch.utils.data.dataloader
import wandb
from omegaconf import OmegaConf
from torch.cuda import Event

from ..utils.backup import backup_project
from ..utils.logging import MetricLogger, setup_logging
from ..utils.misc import import_str, set_seeds
from ..utils.cfg_utils import gen_result_cfg, copy_dataset_files

logger = logging.getLogger()
current_time = time.strftime("%Y-%m-%d_%H-%M-%S", time.localtime())

class TrainingLoopHelper:
    def __init__(self, args):
        self.args = args
        self.cfg = self._setup(args)

        self.g3r_ground_step = None
        if self.cfg.model.get("Ground", False):
            self.g3r_ground_step = self.cfg.model.Ground.init.get("g3r_ground_step", None)
        logger.info(f"models/g3r ground step: {self.g3r_ground_step}")

        self.device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        self.debug_mode = self.cfg.get("debug_mode", False)
        if self.debug_mode:
            self.num_trained_samples = 0
            self.time_costed = 0.0
            self.data_time_costed = 0.0

        # build dataset
        self.dataset = import_str(self.cfg.data.type)(
            project_dir=self.cfg.project_dir,
            cfg=self.cfg,
            debug_mode=self.debug_mode,
        )
        self.trainset_iter = iter(
            torch.utils.data.DataLoader(
                self.dataset.train_image_set,
                num_workers=self.cfg.data.num_workers,
                collate_fn=lambda x: x[0],
                prefetch_factor=self.cfg.data.prefetch_factor,
                pin_memory=True,
            )
        )

        # setup metric logger
        metrics_file = os.path.join(self.cfg.project_dir, "metrics.json")
        self.metric_logger = MetricLogger(delimiter="  ", output_file=metrics_file)

        # setup recon trainer
        self.recon_trainer = import_str(self.cfg.recon_trainer.type)(
            **self.cfg.recon_trainer,
            data_source=self.cfg.data['data_source'],
            num_timesteps=self.dataset.num_img_timesteps,
            model_config=self.cfg.model,
            num_train_images=len(self.dataset.train_image_set),
            num_full_images=len(self.dataset.full_image_set),
            test_set_indices=self.dataset.test_timesteps,
            scene_aabb=self.dataset.get_aabb().reshape(2, 3),
            device=self.device,
            model_path=self.cfg.project_dir
        )

        if self.args.load_from:
            self.recon_trainer.resume_from_checkpoint(ckpt_path=resume_from, load_only_model=True)
            self.recon_trainer.step = 0
            logger.info(f"Loading only model from {resume_from}, " f"Starting at step {self.recon_trainer.step}")
        else:
            # first try to resume
            metadata_path = os.path.join(self.cfg.project_dir, "training_metadata.json")
            if os.path.exists(metadata_path):
                with open(metadata_path, "r") as f:
                    metadata = json.load(f)
                num_finished_step = metadata["next_step"]
                resume_middle = os.path.join(self.cfg.project_dir, "trained_model", f"checkpoint_{(num_finished_step):05d}.pth")
                resume_final = os.path.join(self.cfg.project_dir, "trained_model", f"checkpoint_final.pth")

                if os.path.exists(resume_middle):
                    resume_from = resume_middle
                elif os.path.exists(resume_final):
                    resume_from = resume_final
                else:
                    raise ValueError(f"Resume checkpoint {resume_from} or {resume_final} does not exist, please check the path")

                self.recon_trainer.resume_from_checkpoint(ckpt_path=resume_from, load_only_model=False)
                self.recon_trainer.step += 1
                logger.info(f"Resuming training from {resume_from}, " f"starting at step {self.recon_trainer.step}")
                if self.recon_trainer.num_iters <= self.recon_trainer.step:
                    self.recon_trainer.num_iters = self.recon_trainer.step + 10000
                    logger.info(f'[WARNING] invalid resume checkpoint, set num_iters to {self.recon_trainer.step + 10000}')
            else:
                self.recon_trainer.init_gaussians_from_dataset(dataset=self.dataset)
                self.recon_trainer.init_misc_models_from_dataset(dataset=self.dataset)
                self.recon_trainer.initialize_optimizer()
                logger.info(
                    f"Training from scratch, initializing gaussians from dataset, "
                    f"starting at step {self.recon_trainer.step}"
                )

        self.all_iters = np.arange(self.recon_trainer.step, self.recon_trainer.num_iters)
        self.start_engine_infer_iter = 40000

        # save information for simulator render in config.yaml
        output_dir = os.path.join(args.output_root, args.project, args.run_name)
        self._save_cfg(output_dir)
        copy_dataset_files(self.cfg)

    def _setup(self, args):
        # get config
        cfg = OmegaConf.load(args.config_file)

        # parse datasets
        args_from_cli = OmegaConf.from_cli(args.opts)
        if "dataset" in args_from_cli:
            cfg.dataset = args_from_cli.pop("dataset")

        assert "dataset" in cfg or "data" in cfg, "Please specify dataset in config or data in config"

        if "dataset" in cfg:
            dataset_type = cfg.pop("dataset")
            dataset_cfg = OmegaConf.load(os.path.join("configs", "datasets", f"{dataset_type}.yaml"))
            # merge data
            cfg = OmegaConf.merge(cfg, dataset_cfg)

        # merge cli
        cfg = OmegaConf.merge(cfg, args_from_cli)
        log_dir = os.path.join(args.output_root, args.project, args.run_name)

        # update config and create log dir
        cfg.project_dir = log_dir
        os.makedirs(log_dir, exist_ok=True)
        for folder in [
            "configs",
            "log_images",
            "videos",
            "metrics",
            "buffer_maps",
            "trained_model"
        ]:
            os.makedirs(os.path.join(log_dir, folder), exist_ok=True)

        # setup wandb
        if args.enable_wandb:
            # sometimes wandb fails to init in cloud machines, so we give it several (many) tries
            while (
                wandb.init(
                    project=args.project,
                    entity=args.entity,
                    sync_tensorboard=True,
                    settings=wandb.Settings(start_method="fork"),
                )
                is not wandb.run
            ):
                continue
            wandb.run.name = args.run_name
            wandb.run.save()
            wandb.config.update(OmegaConf.to_container(cfg, resolve=True))
            wandb.config.update(args)

        # setup random seeds
        set_seeds(cfg.seed)

        global logger
        setup_logging(output=log_dir, level=logging.INFO, time_string=current_time)
        logger.info("\n".join("%s: %s" % (k, str(v)) for k, v in sorted(dict(vars(args)).items())))

        # Backup codes
        # backup_project(
        #     os.path.join(log_dir, "backup"),
        #     "./reconic",
        #     ["cli", "datasets", "engines", "models", "pipelines", "trainers", "utils"],
        #     [".py", ".h", ".cpp", ".cuh", ".cu", ".sh", ".yaml"],
        # )
        return cfg

    def _save_cfg(self, output_dir):
        # reconic simulator need this
        self.cfg.data.lidar_source.aabb = self.dataset.aabb.tolist()
        # append result to config yaml
        result_cfg = gen_result_cfg(self.cfg)
        final_cfg = OmegaConf.merge(self.cfg, result_cfg)

        # save config
        # logger.info(f"Config:\n{OmegaConf.to_yaml(final_cfg)}")
        saved_cfg_path = os.path.join(output_dir, "configs", "config_sim.yaml")
        with open(saved_cfg_path, "w") as f:
            OmegaConf.save(config=final_cfg, f=f)

        # 直接从内存保存 npz + slim yaml，避免后续 init 时重新解析大 yaml
        try:
            from reconic.simulator.extract_results_cache import extract_results_cache_from_cfg
            extract_results_cache_from_cfg(final_cfg, saved_cfg_path)
        except Exception as e:
            print(f"[WARNING] extract_results_cache failed (non-fatal): {e}")

    def _get_render_keys(self):
        # define render keys
        render_keys = [
            "gt_rgbs",
            "rgbs",
            "Background_rgbs",
            "Ground_rgbs",
            "Dynamic_rgbs",
            # "RigidNodes_rgbs",
            # "DeformableNodes_rgbs",
            # "SMPLNodes_rgbs",
            # "depths",
            # "Background_depths",
            # "Ground_depths",
            # "Dynamic_depths",
            # "RigidNodes_depths",
            # "DeformableNodes_depths",
            # "SMPLNodes_depths",
            # "mask"
        ]
        if self.cfg.render.vis_lidar:
            render_keys.insert(0, "lidar_on_images")
        if self.cfg.render.vis_sky:
            render_keys += ["rgb_sky_blend", "rgb_sky"]
        if self.cfg.render.vis_error:
            render_keys.insert(render_keys.index("rgbs") + 1, "rgb_error_maps")
        return render_keys

    def _metric_logging_step(self, outputs, loss_dict, image_info):
        with torch.no_grad():
            # cal stats
            metric_dict = self.recon_trainer.compute_metrics(
                outputs=outputs,
                image_info=image_info,
            )
        self.metric_logger.update(**{"train_metrics/" + k: v.item() for k, v in metric_dict.items()})
        self.metric_logger.update(
            **{"train_stats/gaussian_num_" + k: v for k, v in self.recon_trainer.get_gaussian_count().items()}
        )
        self.metric_logger.update(**{"losses/" + k: v.item() for k, v in loss_dict.items()})
        self.metric_logger.update(
            **{"train_stats/lr_" + group["name"]: group["lr"] for group in self.recon_trainer.optimizer.param_groups}
        )

    def _save_checkpoint_step(self, step):
        num_finished_step = step + 1
        do_save = num_finished_step > 0 and (
            (num_finished_step % self.cfg.logging.saveckpt_freq == 0)
            or (num_finished_step == self.recon_trainer.num_iters)
        )
        if do_save:
            self.recon_trainer.save_checkpoint(
                log_dir=os.path.join(self.cfg.project_dir, "trained_model"),
                save_only_model=False,
                is_final=num_finished_step == self.recon_trainer.num_iters,
            )

            metadata = {
                "next_step": int(num_finished_step),
            }
            with open(os.path.join(self.cfg.project_dir, "training_metadata.json"), "w") as f:
                json.dump(metadata, f)

    def _cache_image_error_step(self, step):
        if (
            step > 0
            and self.recon_trainer.optim_general.cache_buffer_freq > 0
            and step % self.recon_trainer.optim_general.cache_buffer_freq == 0
        ):
            from ..models.video_utils import render_images

            logger.info("Caching image error...")
            self.recon_trainer.set_eval()
            with torch.no_grad():
                self.dataset.pixel_source.update_downscale_factor(1 / self.dataset.pixel_source.buffer_downscale)
                render_results = render_images(
                    trainer=self.recon_trainer,
                    dataset=self.dataset.full_image_set,
                )
                self.dataset.pixel_source.reset_downscale_factor()
                self.dataset.pixel_source.update_image_error_maps(render_results)

                # save error maps
                merged_error_video = self.dataset.pixel_source.get_image_error_video(self.dataset.layout)
                imageio.mimsave(
                    os.path.join(self.cfg.project_dir, "buffer_maps", f"buffer_maps_{step}.mp4"),
                    merged_error_video,
                    fps=self.cfg.render.fps,
                )
            logger.info("Done caching rgb error maps")

    def train(self):
        if self.debug_mode:
            start_training_event = Event(enable_timing=True)
            get_data_event = Event(enable_timing=True)
            forward_backward_event = Event(enable_timing=True)
            post_training_event = Event(enable_timing=True)

            check_start_event = Event(enable_timing=True)
            check_end_event = Event(enable_timing=True)

        self.run_before_train()

        if self.cfg.get("joint_training_cfg", None) is not None:
            self.start_engine_infer_iter=self.cfg.joint_training_cfg.start_engine_infer_at
        begin_downsample = False
        for step in self.metric_logger.log_every(self.all_iters, 
                                                 self.cfg.logging.print_freq, 
                                                 start_engine_infer_at=self.start_engine_infer_iter):
            if self.debug_mode:                                     
                self.run_validation_step(step)
            self.run_before_train_step(step)
            if self.debug_mode:
                start_training_event.record()
            if step >= self.cfg.joint_training_cfg.start_engine_infer_at and not begin_downsample:
                begin_downsample = True
                self.dataset.train_image_set.datasource.update_difix_downsample()
                self.trainset_iter._dataset.datasource.update_difix_downsample()
                self.trainset_iter = iter(
                    torch.utils.data.DataLoader(
                        self.dataset.train_image_set,
                        num_workers=self.cfg.data.num_workers,
                        collate_fn=lambda x: x[0],
                        prefetch_factor=self.cfg.data.prefetch_factor,
                        pin_memory=True,
                    )
                )
            train_data = self.get_next_train_data()
            if self.debug_mode:
                logger.info(f"[data][{step}] current image_id: {int(train_data[1].image_index.item())}, with len {len(train_data)}")
                get_data_event.record()
            outputs, loss_dict = self.forward_step(step, train_data)
            # if (step > 0 and step < 20001) and (step % 1000 == 0):
            #     save_path = os.path.join(self.cfg.project_dir, "difix_train_data", str(step))
            #     os.makedirs(save_path ,exist_ok=True)
            #     self.run_generative_model_train_data(save_path)

            # check nan or inf
            if self.debug_mode:
                check_start_event.record()
            for k, v in loss_dict.items():
                if torch.isnan(v).any():
                    raise ValueError(f"NaN detected in loss {k} at step {step}")
                if torch.isinf(v).any():
                    raise ValueError(f"Inf detected in loss {k} at step {step}")
            if self.debug_mode:
                check_end_event.record()

            self.backward_step(step, outputs, loss_dict)
            if self.debug_mode:
                forward_backward_event.record()

            self.run_after_train_step(step, train_data, outputs, loss_dict)
            self.run_after_step_finished(step, train_data, outputs, loss_dict)

            if self.debug_mode:
                post_training_event.record()

            if self.debug_mode:
                torch.cuda.synchronize()
                self.num_trained_samples += 1
                self.time_costed += start_training_event.elapsed_time(post_training_event)
                self.data_time_costed += start_training_event.elapsed_time(get_data_event)
                if self.num_trained_samples % self.cfg.logging.print_freq == 0:
                    logger.info("[profile] get data time: %f", start_training_event.elapsed_time(get_data_event))
                    logger.info(
                        "[profile] forward backward time: %f", get_data_event.elapsed_time(forward_backward_event)
                    )
                    logger.info("[profile] loss check time: %f", check_start_event.elapsed_time(check_end_event))
                    logger.info(
                        "[profile] post training time: %f", forward_backward_event.elapsed_time(post_training_event)
                    )
                    logger.info(
                        "[profile] data producting speed(ms/sample): %f",
                        self.data_time_costed / self.num_trained_samples,
                    )
                    logger.info(
                        "[profile] data consuming speed(samples/s): %f",
                        self.num_trained_samples / (self.time_costed / 1000),
                    )

        self.run_after_train()

    def run_before_train(self):
        print("Start training...")

    def run_validation_step(self, step):
        if step % self.cfg.logging.vis_freq == 0 and self.cfg.logging.vis_freq > 0:
            logger.info("Visualizing...")
            from ..models.video_utils import render_images

            vis_timestep = np.linspace(
                0,
                self.dataset.num_img_timesteps,
                self.recon_trainer.num_iters // self.cfg.logging.vis_freq + 1,
                endpoint=False,
                dtype=int,
            )[step // self.cfg.logging.vis_freq]
            with torch.no_grad():
                image_output_pth = os.path.join(self.cfg.project_dir, "log_images", f"step_{step}.png")
                save_videos_config = {
                    "num_timestamps": 1,
                    "num_cams": self.dataset.pixel_source.num_cams,
                    "keys": self._get_render_keys(),
                    "fps": self.cfg.render.fps,
                    "save_separate_video": self.cfg.logging.save_seperate_video,
                    "save_images": False,
                }
                render_images(
                    trainer=self.recon_trainer,
                    dataset=self.dataset.full_image_set,
                    compute_metrics=True,
                    compute_error_map=self.cfg.render.vis_error,
                    vis_indices=[
                        vis_timestep * self.dataset.pixel_source.num_cams + i
                        for i in range(self.dataset.pixel_source.num_cams)
                    ],
                    render_keys=self._get_render_keys(),
                    save_path=image_output_pth,
                    layout_fn=self.dataset.layout,
                    save_videos_config=save_videos_config,
                )

    def run_before_train_step(self, step):
        # prepare for training
        fix_ground = (self.g3r_ground_step is not None and 
                      self.g3r_ground_step < step < self.start_engine_infer_iter)

        self.recon_trainer.set_train(step, fix_ground)
        self.recon_trainer.preprocess_per_train_step(step=step)
        self.recon_trainer.optimizer_zero_grad()  # zero grad

    def get_next_train_data(self):
        train_data = next(self.trainset_iter)
        train_data[1].to(self.device)
        train_data[2].to(self.device)
        if len(train_data) > 3:
            train_data[3].to(self.device)
            train_data[4].to(self.device)

        return train_data

    def forward_step(self, step, train_data):
        raise NotImplementedError()

    def backward_step(self, step, outputs, loss_dict):
        raise NotImplementedError()

    def run_after_train_step(self, step, train_data, outputs, loss_dict):
        self.recon_trainer.postprocess_per_train_step(step=step)

    def run_after_train(self):
        # from .eval import do_evaluation

        # do_evaluation(
        #     step=self.recon_trainer.num_iters,
        #     cfg=self.cfg,
        #     trainer=self.recon_trainer,
        #     dataset=self.dataset,
        #     render_keys=self._get_render_keys(),
        # )
        pass

    def run_after_step_finished(self, step, train_data, outputs, loss_dict):
        image_info = train_data[1]
        if outputs is not None:
            self._metric_logging_step(outputs, loss_dict, image_info)
        self._save_checkpoint_step(step)
        self._cache_image_error_step(step)
        torch.cuda.empty_cache()

    def run_generative_model_train_data(self, save_path):
        config_path = os.path.join(self.cfg.project_dir, "config.yaml")
        saved_state_dict = self.recon_trainer.state_dict(only_model=False)
        simulator = ReconicSimulator(config_path, state_dict=saved_state_dict)
        render_origin(simulator, save_path, 
                        distortion=False, save_image=True, save_video=False)
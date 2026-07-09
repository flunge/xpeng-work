import os
import torch
import cv2
import numpy as np

from detectron2.checkpoint import DetectionCheckpointer
from detectron2.config import get_cfg
from detectron2.modeling import build_model
from detectron2.projects.deeplab import add_deeplab_config
from detectron2.data import transforms as T
from detectron2.data import MetadataCatalog
from detectron2.structures import Instances

from data_mining.Mask2Former.mask2former import add_maskformer2_config
from data_mining.Mask2Former.mask2former_video import add_maskformer2_video_config
from data_mining.Mask2Former.mask2former_video.visualizer import TrackVisualizer

from data_mining.LOMM.lomm import add_minvis_config, add_dvis_config, add_lomm_config
from data_mining.LOMM.demo_video.visualizer import TrackVisualizer as LOMMTrackVisualizer

from data_mining.Mask2Former.mask2former.modeling import ensure_backbone_registered

class SegGenerator:
    def __init__(self, cfg):
        ensure_backbone_registered()
        ### Prepare models and assets
        code_dir = os.path.dirname(os.path.abspath(__file__))
        mask2former_cfg_path = os.path.join(code_dir, 
            "data_mining/Mask2Former/maskformer2_swin_large_IN21k_384_bs16_300k.yaml")
        mask2former_model_path = os.path.join(cfg["pretrained_model_path"], 
            "mask2former_mapillary_vistas_swin_L.pkl")
        
        mask2former_video_cfg_path = os.path.join(code_dir, 
            "data_mining/Mask2Former/video_maskformer2_swin_large_IN21k_384_bs16_8ep.yaml")
        mask2former_video_model_path = os.path.join("/workspace/group_share/adc-sim/users/zf/recon_pretrained_models",
            "video_mask2former_youtube_swin_L_in21k_6k.pkl")
        
        lomm_cfg_path = os.path.join(code_dir, 
            "data_mining/LOMM/configs/ytvis19/vit_adapter/LOMM_Online_ViTL.yaml")
        lomm_model_path = os.path.join("/workspace/group_share/adc-sim/users/zf/recon_pretrained_models",
            "LOMM_online_ytvis19_ViTL_69.1.pth")
        
        self.cfg = cfg
        
        self.mask2former_cfg_path = mask2former_cfg_path
        self.mask2former_model_path = mask2former_model_path
        self.mask2former_video_cfg_path = mask2former_video_cfg_path
        self.mask2former_video_model_path = mask2former_video_model_path
        self.lomm_cfg_path = lomm_cfg_path
        self.lomm_model_path = lomm_model_path
        
        self._model = None
        self._video_model = None
        self._lomm_model = None
        self._video_model_config = None
        self._video_model_input_format = None
        self._video_model_aug = None
        self._video_model_metadata = None
        self._lomm_model_config = None
        self._lomm_model_input_format = None
        self._lomm_model_aug = None
        self._lomm_model_metadata = None
        
        self.segs_path = os.path.join(cfg.clip_path, "segs")
        self.vision_segs_path = os.path.join(cfg.clip_path, "segs_vision")
        self.vision_instance_segs_path = os.path.join(cfg.clip_path, "instance_segs_vision")
        for cam_name in cfg.cam_list:
            os.makedirs(os.path.join(self.segs_path, cam_name), exist_ok=True)

    def load_mask2former_model(self, cfg_path, model_path):
        config = get_cfg()
        add_deeplab_config(config)
        add_maskformer2_config(config)
        config.merge_from_file(cfg_path)
        config.freeze()
        model = build_model(config)
        DetectionCheckpointer(model).load(model_path)
        model.train(False)
        model.eval()
        return model

    def load_mask2former_video_model(self, cfg_path, model_path):
        config = get_cfg()
        add_deeplab_config(config)
        add_maskformer2_config(config)
        add_maskformer2_video_config(config)
        
        config.merge_from_file(cfg_path)
        config.MODEL.WEIGHTS = model_path
        config = config.clone()
        config.freeze()
        
        model = build_model(config)
        model.eval()
        
        checkpointer = DetectionCheckpointer(model)
        checkpointer.load(config.MODEL.WEIGHTS)
        
        self._video_model_config = config
        self._video_model_input_format = config.INPUT.FORMAT
        self._video_model_aug = T.ResizeShortestEdge(
            [config.INPUT.MIN_SIZE_TEST, config.INPUT.MIN_SIZE_TEST], 
            config.INPUT.MAX_SIZE_TEST
        )
        
        self._video_model_metadata = MetadataCatalog.get(
            config.DATASETS.TEST[0] if len(config.DATASETS.TEST) else "__unused"
        )
        
        return model
    
    @property
    def model(self):
        if self._model is None:
            print("[INFO] Loading mask2former model (semantic segmentation)...")
            self._model = self.load_mask2former_model(self.mask2former_cfg_path, self.mask2former_model_path)
            print("[INFO] Mask2former model loaded.")
        return self._model
    
    @property
    def video_model(self):
        if self._video_model is None:
            print("[INFO] Loading mask2former video model (video instance segmentation)...")
            self._video_model = self.load_mask2former_video_model(
                self.mask2former_video_cfg_path, 
                self.mask2former_video_model_path
            )
            print("[INFO] Mask2former video model loaded.")
        return self._video_model
    
    @property
    def video_model_input_format(self):
        if self._video_model_input_format is None:
            _ = self.video_model
        return self._video_model_input_format
    
    @property
    def video_model_aug(self):
        if self._video_model_aug is None:
            _ = self.video_model
        return self._video_model_aug
    
    @property
    def video_model_metadata(self):
        if self._video_model_metadata is None:
            _ = self.video_model
        return self._video_model_metadata
    
    def load_lomm_model(self, cfg_path, model_path):
        config = get_cfg()
        add_deeplab_config(config)
        add_maskformer2_config(config)
        add_maskformer2_video_config(config)
        add_minvis_config(config)
        add_dvis_config(config)
        add_lomm_config(config)
        
        config.merge_from_file(cfg_path)
        config.MODEL.WEIGHTS = model_path
        
        if hasattr(config.MODEL, 'VIT_ADAPTER') and hasattr(config.MODEL.VIT_ADAPTER, 'VIT_WEIGHT'):
            config.MODEL.VIT_ADAPTER.VIT_WEIGHT = None
            if hasattr(config.MODEL.VIT_ADAPTER, 'FREEZE_VIT') and config.MODEL.VIT_ADAPTER.FREEZE_VIT:
                config.MODEL.VIT_ADAPTER.FREEZE_VIT = False
        
        config = config.clone()
        config.freeze()
        
        model = build_model(config)
        model.eval()
        
        weight = torch.load(config.MODEL.WEIGHTS, map_location="cpu")
        if 'model' in weight.keys():
            weight = weight['model']
        model.load_state_dict(weight, strict=True)
        
        self._lomm_model_config = config
        self._lomm_model_input_format = config.INPUT.FORMAT
        self._lomm_model_aug = T.ResizeShortestEdge(
            [config.INPUT.MIN_SIZE_TEST, config.INPUT.MIN_SIZE_TEST], 
            config.INPUT.MAX_SIZE_TEST
        )
        
        self._lomm_model_metadata = MetadataCatalog.get(
            config.DATASETS.TEST[0] if len(config.DATASETS.TEST) else "__unused"
        )
        
        return model
    
    @property
    def lomm_model(self):
        if self._lomm_model is None:
            print("[INFO] Loading LOMM model (video instance segmentation)...")
            self._lomm_model = self.load_lomm_model(self.lomm_cfg_path, self.lomm_model_path)
            print("[INFO] LOMM model loaded.")
        return self._lomm_model
    
    @property
    def lomm_model_input_format(self):
        if self._lomm_model_input_format is None:
            _ = self.lomm_model
        return self._lomm_model_input_format
    
    @property
    def lomm_model_aug(self):
        if self._lomm_model_aug is None:
            _ = self.lomm_model
        return self._lomm_model_aug
    
    @property
    def lomm_model_metadata(self):
        if self._lomm_model_metadata is None:
            _ = self.lomm_model
        return self._lomm_model_metadata

    def generate_segs(self, img):
        inputs = [{"image": torch.from_numpy(img).permute(2, 0, 1).to("cuda")}]
        outputs = self.model(inputs)
        label = outputs[0]["sem_seg"].argmax(dim=0).cpu().numpy()
        return label


    def generate_video_segs_mask2former(self, imgs, return_visualization=False, save_visualization_path=None, fps=10.0):
        with torch.no_grad():
            input_frames = []
            height, width = None, None
            
            for original_image in imgs:
                if self.video_model_input_format == "RGB":
                    original_image = original_image[:, :, ::-1]
                
                if height is None or width is None:
                    height, width = original_image.shape[:2]
                
                image = self.video_model_aug.get_transform(original_image).apply_image(original_image)
                image = torch.as_tensor(image.astype("float32").transpose(2, 0, 1)) # (C, H, W)
                input_frames.append(image)
            
            inputs = {"image": input_frames, "height": height, "width": width}
            
            predictions = self.video_model([inputs])
            
            result_labels = []
            visualized_outputs = []
            
            if isinstance(predictions, dict):
                pred_dict = predictions
            elif isinstance(predictions, list) and len(predictions) > 0:
                pred_dict = predictions[0]
            else:
                raise ValueError(f"Unexpected predictions format: {type(predictions)}")
            
            has_instance_output = "pred_scores" in pred_dict and "pred_labels" in pred_dict and "pred_masks" in pred_dict
            
            if has_instance_output:
                image_size = pred_dict["image_size"]
                pred_scores = pred_dict["pred_scores"]
                pred_labels = pred_dict["pred_labels"]
                pred_masks = pred_dict["pred_masks"]
                
                frame_masks = list(zip(*pred_masks))
                
                for frame_idx in range(len(imgs)):
                    frame_rgb = imgs[frame_idx][:, :, ::-1]
                    visualizer = TrackVisualizer(frame_rgb, self.video_model_metadata)
                    
                    ins = Instances(image_size)
                    if len(pred_scores) > 0:
                        ins.scores = pred_scores
                        ins.pred_classes = pred_labels
                        ins.pred_masks = torch.stack(frame_masks[frame_idx], dim=0)
                    
                    vis_output = visualizer.draw_instance_predictions(predictions=ins)
                    visualized_outputs.append(vis_output)
                    
                    H, W = image_size
                    sem_label = np.zeros((H, W), dtype=np.uint8)
                    
                    if len(pred_scores) > 0 and len(frame_masks[frame_idx]) > 0:
                        frame_masks_tensor = torch.stack(frame_masks[frame_idx], dim=0)  # (num_instances, H, W)
                        frame_masks_np = frame_masks_tensor.cpu().numpy().astype(bool)
                        pred_labels_np = np.array(pred_labels, dtype=np.uint8)
                        
                        for inst_idx in range(len(frame_masks_np)):
                            mask = frame_masks_np[inst_idx]
                            label = pred_labels_np[inst_idx]
                            sem_label[mask] = label
                    
                    result_labels.append(sem_label)
            else:
                raise NotImplementedError(
                    f"Model output format not supported. Available keys: {pred_dict.keys()}"
                )
            
            if len(result_labels) != len(imgs):
                if len(result_labels) == 1 and len(imgs) > 1:
                    result_labels = [result_labels[0]] * len(imgs)
                elif len(result_labels) > len(imgs):
                    result_labels = result_labels[:len(imgs)]
            
            if return_visualization or save_visualization_path:
                if len(visualized_outputs) == 0:
                    if return_visualization:
                        return result_labels, None
                    else:
                        return result_labels
                elif len(visualized_outputs) != len(imgs):
                    if len(visualized_outputs) == 1 and len(imgs) > 1:
                        visualized_outputs = [visualized_outputs[0]] * len(imgs)
                    elif len(visualized_outputs) > len(imgs):
                        visualized_outputs = visualized_outputs[:len(imgs)]
                
                if save_visualization_path:
                    self._save_visualization_to_mp4(visualized_outputs, save_visualization_path, fps)
                
                if return_visualization:
                    return result_labels, visualized_outputs
                else:
                    return result_labels
            else:
                return result_labels
    
    def generate_video_segs_lomm(self, imgs, return_visualization=False, save_visualization_path=None, fps=10.0, keep=False, id_memories=None):
        with torch.no_grad():
            input_frames = []
            height, width = None, None
            
            for original_image in imgs:
                if self.lomm_model_input_format == "RGB":
                    original_image = original_image[:, :, ::-1]
                
                if height is None or width is None:
                    height, width = original_image.shape[:2]
                
                image = self.lomm_model_aug.get_transform(original_image).apply_image(original_image)
                image = torch.as_tensor(image.astype("float32").transpose(2, 0, 1))
                input_frames.append(image)
            
            inputs = {"image": input_frames, "height": height, "width": width, "keep": keep}
            
            predictions = self.lomm_model([inputs])
            
            result_labels = []
            visualized_outputs = []
            
            if isinstance(predictions, dict):
                pred_dict = predictions
            elif isinstance(predictions, list) and len(predictions) > 0:
                pred_dict = predictions[0]
            else:
                raise ValueError(f"Unexpected predictions format: {type(predictions)}")
            
            pred_scores = pred_dict.get("pred_scores", [])
            pred_labels = pred_dict.get("pred_labels", [])
            pred_masks = pred_dict.get("pred_masks", [])
            pred_ids = pred_dict.get("pred_ids", None)
            
            pred_scores_ = []
            pred_labels_ = []
            pred_masks_ = []
            pred_ids_ = []
            for i, score in enumerate(pred_scores):
                if score < 0.3:
                    continue
                pred_scores_.append(pred_scores[i])
                pred_labels_.append(pred_labels[i])
                pred_masks_.append(pred_masks[i])
                if pred_ids is not None:
                    pred_ids_.append(pred_ids[i])
            
            frame_masks = list(zip(*pred_masks_)) if len(pred_masks_) > 0 else [[] for _ in range(len(imgs))]
            
            image_size = pred_dict.get("image_size", (height, width))
            
            # ytvis19_to_mapillary = {
            #     0: 19,   # person -> Person
            #     1: 1,    # giant_panda -> Ground_Animal
            #     2: 1,    # lizard -> Ground_Animal
            #     3: 0,    # parrot -> Bird
            #     4: 65,   # skateboard -> Unlabeled
            #     5: 55,   # sedan -> Car
            #     6: 1,    # ape -> Ground_Animal
            #     7: 1,    # dog -> Ground_Animal
            #     8: 1,    # snake -> Ground_Animal
            #     9: 1,    # monkey -> Ground_Animal
            #     10: 65,  # hand -> Unlabeled
            #     11: 1,   # rabbit -> Ground_Animal
            #     12: 0,   # duck -> Bird
            #     13: 1,   # cat -> Ground_Animal
            #     14: 1,   # cow -> Ground_Animal
            #     15: 1,   # fish -> Ground_Animal
            #     16: 58,  # train -> On_Rails
            #     17: 1,   # horse -> Ground_Animal
            #     18: 1,   # turtle -> Ground_Animal
            #     19: 1,   # bear -> Ground_Animal
            #     20: 57,  # motorbike -> Motorcycle
            #     21: 1,   # giraffe -> Ground_Animal
            #     22: 1,   # leopard -> Ground_Animal
            #     23: 1,   # fox -> Ground_Animal
            #     24: 1,   # deer -> Ground_Animal
            #     25: 0,   # owl -> Bird
            #     26: 65,  # surfboard -> Unlabeled
            #     27: 65,  # airplane -> Unlabeled
            #     28: 61,  # truck -> Truck
            #     29: 1,   # zebra -> Ground_Animal
            #     30: 1,   # tiger -> Ground_Animal
            #     31: 1,   # elephant -> Ground_Animal
            #     32: 65,  # snowboard -> Unlabeled
            #     33: 53,  # boat -> Boat
            #     34: 1,   # shark -> Ground_Animal
            #     35: 1,   # mouse -> Ground_Animal
            #     36: 1,   # frog -> Ground_Animal
            #     37: 0,   # eagle -> Bird
            #     38: 1,   # earless_seal -> Ground_Animal
            #     39: 65,  # tennis_racket -> Unlabeled
            # }
            
            frame_instance_ids = []
            
            if len(imgs) > 0:
                initial_img = imgs[0][:, :, ::-1]  # BGR to RGB
            else:
                initial_img = np.zeros((100, 100, 3), dtype=np.uint8)
            visualizer = LOMMTrackVisualizer(initial_img, self.lomm_model_metadata, id_memories=id_memories)
            
            instance_id_labels = []
            
            for frame_idx in range(len(imgs)):
                H, W = image_size
                sem_label = np.zeros((H, W), dtype=np.uint8)
                instance_id_label = np.zeros((H, W), dtype=np.uint8)
                frame_instance_id_list = []
                
                if len(pred_scores_) > 0 and len(frame_masks[frame_idx]) > 0:
                    frame_masks_tensor = torch.stack(frame_masks[frame_idx], dim=0)  # (num_instances, H, W)
                    frame_masks_np = frame_masks_tensor.cpu().numpy().astype(bool)
                    pred_labels_np = np.array(pred_labels_, dtype=np.uint8)
                    
                    for inst_idx in range(len(frame_masks_np)):
                        mask = frame_masks_np[inst_idx]
                        # ytvis_label = pred_labels_np[inst_idx]
                        # mapillary_label = ytvis19_to_mapillary.get(ytvis_label, 65)
                        # sem_label[mask] = mapillary_label
                        label = pred_labels_np[inst_idx]
                        sem_label[mask] = label
                        
                        if np.any(mask):
                            if pred_ids is not None and inst_idx < len(pred_ids_):
                                instance_id = pred_ids_[inst_idx]
                                if isinstance(instance_id, torch.Tensor):
                                    instance_id = instance_id.item()
                                continuous_id = visualizer._get_continuous_id(instance_id)
                                frame_instance_id_list.append(continuous_id)
                                
                                # person(0), sedan(5), motorbike(20), truck(28)
                                if label in [0, 5, 20, 28]:
                                    instance_id_label[mask] = continuous_id
                
                result_labels.append(sem_label)
                frame_instance_ids.append(frame_instance_id_list)
                instance_id_labels.append(instance_id_label)
                
                if return_visualization or save_visualization_path:
                    frame_rgb = imgs[frame_idx][:, :, ::-1]
                    from detectron2.utils.visualizer import VisImage
                    visualizer.output = VisImage(frame_rgb, scale=visualizer.output.scale)
                    
                    ins = Instances(image_size)
                    if len(pred_scores_) > 0 and len(frame_masks[frame_idx]) > 0:
                        ins.scores = pred_scores_
                        ins.pred_classes = pred_labels_
                        ins.pred_masks = torch.stack(frame_masks[frame_idx], dim=0)
                    
                    vis_output = visualizer.draw_instance_predictions(predictions=ins, ids=pred_ids_ if pred_ids is not None else None)
                    visualized_outputs.append(vis_output)
            
            if save_visualization_path and len(visualized_outputs) > 0:
                self._save_visualization_to_mp4(visualized_outputs, save_visualization_path, fps)
            
            if not return_visualization and not save_visualization_path:
                visualized_outputs = None
            
            return result_labels, visualized_outputs, frame_instance_ids, instance_id_labels


    def _save_visualization_to_mp4(self, visualized_outputs, output_path, fps=10.0):
        if len(visualized_outputs) == 0:
            return
        
        H, W = visualized_outputs[0].height, visualized_outputs[0].width
        
        output_dir = os.path.dirname(output_path)
        if output_dir and not os.path.exists(output_dir):
            os.makedirs(output_dir, exist_ok=True)
        
        fourcc = cv2.VideoWriter_fourcc(*"mp4v")
        out = cv2.VideoWriter(output_path, fourcc, fps, (W, H), True)
        
        for vis_output in visualized_outputs:
            frame = vis_output.get_image()[:, :, ::-1]
            out.write(frame)
        
        out.release()
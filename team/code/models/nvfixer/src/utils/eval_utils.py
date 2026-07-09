import numpy as np
import torch
from PIL import Image
from torchvision import transforms

from utils.training_utils import calculate_psnr


def evaluate_test_psnr(
    accelerator,
    dataset_val,
    dl_val,
    predict_fn,
    set_eval_fn=None,
    set_train_fn=None,
):
    """
    Evaluate PSNR on the whole test split.

    Args:
        accelerator: Accelerate Accelerator instance.
        dataset_val: Validation dataset.
        dl_val: Validation dataloader.
        predict_fn: Callable(batch_val) -> prediction tensor of shape [B, C, H, W].
        set_eval_fn: Optional callable to switch model to eval mode.
        set_train_fn: Optional callable to switch model back to train mode.

    Returns:
        dict: eval logs containing eval_psnr/overall and eval_psnr/cam_xxx.
    """
    eval_logs = {}
    if len(dataset_val) == 0:
        print("[EVAL] test set is empty, skip PSNR evaluation.", flush=True)
        return eval_logs

    eval_cam_names = list(
        getattr(dataset_val, "cam_names", ("cam0", "cam2", "cam3", "cam4", "cam5", "cam6", "cam7"))
    )
    cam_to_idx = {cam: i for i, cam in enumerate(eval_cam_names)}
    local_psnr_sum = torch.zeros(len(eval_cam_names), device=accelerator.device, dtype=torch.float64)
    local_psnr_cnt = torch.zeros(len(eval_cam_names), device=accelerator.device, dtype=torch.float64)
    local_eval_samples = 0
    local_eval_batches = 0

    print(
        f"[EVAL][RANK {accelerator.process_index}] start: "
        f"dataset_val_len={len(dataset_val)}, local_dl_batches={len(dl_val)}",
        flush=True,
    )

    if set_eval_fn is not None:
        set_eval_fn()

    try:
        with torch.no_grad():
            for batch_val in dl_val:
                local_eval_batches += 1
                x_tgt_val = batch_val["output_pixel_values"]
                x_pred_val = predict_fn(batch_val)

                batch_size_val = x_pred_val.shape[0]
                local_eval_samples += int(batch_size_val)
                for b in range(batch_size_val):
                    cam_name = batch_val["cam_name"][b]
                    origin_w = int(batch_val["origin_input_width"][b])
                    origin_h = int(batch_val["origin_input_height"][b])

                    pred_img = transforms.ToPILImage()(
                        x_pred_val[b].detach().cpu().float() * 0.5 + 0.5
                    ).resize((origin_w, origin_h), Image.LANCZOS)
                    tgt_img = transforms.ToPILImage()(
                        x_tgt_val[b].detach().cpu().float() * 0.5 + 0.5
                    ).resize((origin_w, origin_h), Image.LANCZOS)

                    mask_np = batch_val["mask"][b, 0].detach().cpu().numpy().astype(np.uint8)
                    if mask_np.shape[:2] != (origin_h, origin_w):
                        mask_np = np.array(
                            Image.fromarray(mask_np).resize((origin_w, origin_h), Image.NEAREST)
                        )

                    psnr_val = calculate_psnr(pred_img, tgt_img, mask_np)
                    if np.isfinite(psnr_val) and cam_name in cam_to_idx:
                        cam_idx = cam_to_idx[cam_name]
                        local_psnr_sum[cam_idx] += float(psnr_val)
                        local_psnr_cnt[cam_idx] += 1.0
    finally:
        if set_train_fn is not None:
            set_train_fn()

    print(
        f"[EVAL][RANK {accelerator.process_index}] done: "
        f"local_samples={local_eval_samples}, local_batches={local_eval_batches}",
        flush=True,
    )

    global_psnr_sum = accelerator.reduce(local_psnr_sum, reduction="sum")
    global_psnr_cnt = accelerator.reduce(local_psnr_cnt, reduction="sum")

    if accelerator.is_main_process:
        total_sum = 0.0
        total_cnt = 0.0
        for cam_idx, cam_name in enumerate(eval_cam_names):
            cnt = float(global_psnr_cnt[cam_idx].item())
            if cnt > 0:
                s = float(global_psnr_sum[cam_idx].item())
                eval_logs[f"eval_psnr/cam_{cam_name}"] = s / cnt
                total_sum += s
                total_cnt += cnt
        if total_cnt > 0:
            eval_logs["eval_psnr/overall"] = total_sum / total_cnt
        else:
            print("[EVAL] no valid PSNR values found on test set.", flush=True)

    return eval_logs

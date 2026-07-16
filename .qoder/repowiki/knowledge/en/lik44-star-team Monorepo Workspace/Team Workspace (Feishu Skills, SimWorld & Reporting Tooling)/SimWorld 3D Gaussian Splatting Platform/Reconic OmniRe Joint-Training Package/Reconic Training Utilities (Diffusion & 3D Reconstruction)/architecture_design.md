Flat collection of independent utility modules with no internal package hierarchy; each file is a self-contained namespace imported directly by higher-level training code.

- `basic_modules.py` provides the core diffusion backbone: dimension-generic `conv_nd`/`avg_pool_nd`, `GroupNorm32`, `Upsample`/`Downsample`, and a `ResBlock` whose final conv is zero-initialized via `zero_module` — the canonical DDPM-style residual block reused across models.
- `model_utils.py` defines a `LazyPipeline` base class plus concrete `GroundingDINOPipeline` and `SAMPipeline` subclasses that lazily load HuggingFace / HF Hub models on first call; this is the only place in the module that imports external vision backends (`groundingdino`, `transformers`).
- `camera.py` owns pose/trajectory math: `interpolate_poses` (translation + Slerp), `look_at_rotation`, and a registry-driven dispatcher `get_interp_novel_trajectories` routing to standardized or custom generators; it also wraps `gsplat.rasterization` for top-down rendering.
- `geometry.py` holds pure tensor/numpy primitives (homogeneous transforms, 6D→matrix rotation, uniform sphere sampling) with no side effects.
- `cfg_utils.py` bridges raw dataset JSON/YAML into an OmegaConf object (`gen_result_cfg`) and copies essential scene files for downstream sim/debug runs.
- `recorder.py` implements a TensorBoard `Recorder` that maintains EMA-smoothed loss/PSNR per camera and logs model point counts.
- `visualization.py` exposes dataset-specific multi-camera tiling layouts (`layout_waymo`, `layout_nuscenes`, `layout_xpeng`, …) plus depth/colormap utilities; `misc.py` adds distributed-aware helpers (`is_main_process`, `get_global_rank`) and Open3D PLY exporters.

Dependency direction is one-way: these utils import from sibling packages (`..datasets.*`, `gsplat.rendering`, `torch.utils.tensorboard`) but nothing inside the package depends on them, making them leaf consumers rather than providers.
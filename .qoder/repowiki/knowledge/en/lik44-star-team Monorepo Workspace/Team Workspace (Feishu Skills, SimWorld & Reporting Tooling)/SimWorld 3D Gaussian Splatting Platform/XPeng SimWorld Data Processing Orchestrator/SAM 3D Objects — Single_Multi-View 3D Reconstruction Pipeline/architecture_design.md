Two-layer entry point over a self-contained package:
- `notebook/inference.py` exposes a thin `Inference` class that loads a Hydra/OmegaConf YAML config, runs a whitelist/blacklist safety check on `_target_` entries, instantiates `sam3d_objects.pipeline.inference_pipeline_pointmap.InferencePipelinePointMap`, merges mask into RGBA, and returns a dict with `gs` (GaussianSplatting), `glb`, `coords`, etc.
- `run_inference.py` / `demo.py` are CLI wrappers: they discover images/masks under `--input_path`, optionally split by `--mask_prompt`, call `Inference.__call__` for single-view or `pipeline.run_multi_view(..., mode='multidiffusion')` for multi-view, then write `result.ply` and/or `result.glb` into `visualization/`.

Core library lives in `sam3d_objects/` with clear sub-packages:
- `model/backbone/tdfy_dit/` — the generative backbone: `models/structured_latent_vae/` defines SLatEncoder + decoders (`decoder_gs`, `decoder_mesh`, `decoder_rf`) plus sparse structure flow models; `modules/sparse/` provides spconv-backed sparse conv/attention/transformer blocks; `renderers/` holds gaussian/octree renderers; `representations/` groups gs/mesh/octree/radiance-field primitives.
- `model/backbone/generator/flow_matching/` and `shortcut/` implement alternative sampling backends layered on top of the DiT latent space.
- `model/layers/llama3/ff.py` reuses LLaMA-style feed-forward blocks inside the transformer stack.
- `data/dataset/tdfy/` contains image/mask transforms, pose targets, and a preprocessor feeding the DiT.
- `pipeline/` composes preprocessing (`preprocess_utils`, `multi_view_utils`, `depth_models.moge`), the main `inference_pipeline_pointmap.py` (pointmap-aware variant) and `inference_pipeline.py`, plus layout post-optimization helpers.
- `utils/visualization/` bundles Kaolin/Plotly scene visualizers and mesh/image helpers.

Dependency direction is strictly inward: notebooks → `sam3d_objects.pipeline.*` → `sam3d_objects.model.backbone.tdfy_dit.*`; data loaders depend only on `sam3d_objects.data.*`. The package root `__init__.py` guards heavy initialization behind `LIDRA_SKIP_INIT` so lightweight tools can import without loading the full model graph.
import os

gs_mode = os.getenv("GS_MODE")
if gs_mode == "render":
    from .base_render import BasicTrainer_render
    from .base_render import BasicTrainer_render as BasicTrainer
    from .scene_graph import MultiTrainer
    from .single import SingleTrainer

    __all__ = [
        "BasicTrainer_render",
        "BasicTrainer",
        "MultiTrainer",
        "SingleTrainer",
    ]
else:
    # 默认情况（包括 GS_MODE 不存在或其他值）
    from .base import BasicTrainer
    from .scene_graph import MultiTrainer
    from .single import SingleTrainer

    __all__ = [
        "BasicTrainer",
        "MultiTrainer",
        "SingleTrainer",
    ]
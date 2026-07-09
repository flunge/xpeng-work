import os

gs_mode = os.getenv("GS_MODE")
if gs_mode == "render":
    # from .deformgs import DeformableGaussians
    from .pvg_render import PeriodicVibrationGaussians_render
    from .pvg_render import PeriodicVibrationGaussians_render as PeriodicVibrationGaussians
    from .scaffold import ScaffoldGaussians
    from .vanilla_render import VanillaGaussians_render
    from .vanilla_render import VanillaGaussians_render as VanillaGaussians


    __all__ = [
        "PeriodicVibrationGaussians_render", 
        "PeriodicVibrationGaussians",
        "ScaffoldGaussians", 
        "VanillaGaussians_render",
        "VanillaGaussians",
    ]
else:
    # 默认情况（包括 GS_MODE 不存在或其他值）
    # from .deformgs import DeformableGaussians
    from .pvg import PeriodicVibrationGaussians
    from .scaffold import ScaffoldGaussians
    from .vanilla import VanillaGaussians

    __all__ = ["PeriodicVibrationGaussians", "ScaffoldGaussians", "VanillaGaussians"]
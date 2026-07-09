import os

gs_mode = os.getenv("GS_MODE")
if gs_mode == "render":
    from .rigid_render import RigidNodes_render
    from .rigid_render import RigidNodes_render as RigidNodes
    # from .smpl_render import SMPLNodes_render

    __all__ = ["RigidNodes_render", "RigidNodes"]
else:
    # 默认情况（包括 GS_MODE 不存在或其他值）
    # from .deformable import DeformableNodes
    from .rigid import RigidNodes
    from .smpl import SMPLNodes

    __all__ = ["RigidNodes", "SMPLNodes"]
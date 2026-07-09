from yacs.config import CfgNode as CN

_C = CN()

# max number of keyframes
_C.BUFFER_SIZE = 4096

# bias patch selection towards high gradient regions?
_C.CENTROID_SEL_STRAT = 'RANDOM' # 'RANDOM'

# VO config (increase for better accuracy)
_C.PATCHES_PER_FRAME = 160
_C.REMOVAL_WINDOW = 20
_C.OPTIMIZATION_WINDOW = 12
_C.PATCH_LIFETIME = 12

# threshold for keyframe removal
_C.KEYFRAME_INDEX = 4
_C.KEYFRAME_THRESH = 12.5

# camera motion model
_C.MOTION_MODEL = 'DAMPED_LINEAR'
_C.MOTION_DAMPING = 0.5

_C.MIXED_PRECISION = False

# Loop closure
_C.LOOP_CLOSURE = False
_C.BACKEND_THRESH = 64.0
_C.MAX_EDGE_AGE = 1000
_C.GLOBAL_OPT_FREQ = 15

# Classic loop closure
_C.CLASSIC_LOOP_CLOSURE = False
_C.LOOP_CLOSE_WINDOW_SIZE = 3
_C.LOOP_RETR_THRESH = 0.04

# network
_C.network = "/workspace/group_share/adc-sim/users/zf/optimization_models/dpvo.pth"
_C.name = "campose"
_C.stride = 1
_C.skip = 0
_C.num_align = 50
_C.qa_mask_ratio = 0.8
_C.qa_continuous_fail_num = 10

cfg = _C

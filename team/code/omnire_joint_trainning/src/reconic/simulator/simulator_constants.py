"""Shared constants for ReconicSimulator."""

LABEL2CAMERA = {
    0: "cam0",
    2: "cam2",
    3: "cam3",
    4: "cam4",
    5: "cam5",
    6: "cam6",
    7: "cam7",
}

CAMERA2LABEL = {name: cam_id for cam_id, name in LABEL2CAMERA.items()}

RIGID_NODE_CLASSES = ("RigidNodes", "RigidNodesLight", "SMPLNodes", "DeformableNodes")
COLLISION_RIGID_CLASSES = ("RigidNodes", "RigidNodesLight")

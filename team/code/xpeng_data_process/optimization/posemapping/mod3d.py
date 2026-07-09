import numpy as np
from scipy.spatial import cKDTree

from .pose import Pose


class BBox3D:
    def __init__(self, bbox3d_dict:dict):
        self.length = 0
        self.width = 0
        self.height = 0
        self.center = np.array([0, 0, 0])
        self.radius = 0
        self.transform_vehicle_to_object = Pose.identity()
        if bbox3d_dict:
            self.parse_bbox3d_dict(bbox3d_dict)

    def parse_bbox3d_dict(self, bbox3d_dict:dict):
        x = bbox3d_dict['x']
        y = bbox3d_dict['y']
        z = bbox3d_dict['z']
        self.length = bbox3d_dict['length'] + 0.6
        self.width = bbox3d_dict['width'] + 0.4
        self.height = bbox3d_dict['height'] + 0.2
        q = bbox3d_dict['quaternion']
        quaternion = np.array([q['x'], q['y'], q['z'], q['w']])
        self.center = np.array([x, y, z+0.1])
        self.radius = np.sqrt(self.length**2 + self.width**2 + self.height**2) / 2
        self.transform_vehicle_to_object = Pose.from_q_t(quaternion, self.center).inverse()

    def get_inner_point_indices(self, points:np.ndarray, kdtree:cKDTree):
        indices = kdtree.query_ball_point(self.center, self.radius)
        ball_points = points[indices]
        object_points = self.transform_vehicle_to_object.transform_points(ball_points)
        inner_indices = np.where(np.all(np.abs(object_points) < np.array([self.length/2, self.width/2, self.height/2]), axis=1))
        indices = np.asarray(indices)
        return indices[inner_indices]

class BBox4D(BBox3D):
    def __init__(self, bbox3d_dict:dict, velocity_dict:dict):
        self.velocity = np.array([0, 0, 0])
        super().__init__(bbox3d_dict)
        if velocity_dict:
            self.parse_velocity_dict(velocity_dict)

    def parse_velocity_dict(self, velocity_dict:dict):
        wrold_ekf = velocity_dict['world_ekf']
        self.velocity = np.array([wrold_ekf['x'], wrold_ekf['y'], wrold_ekf['z']])
        speed = np.linalg.norm(self.velocity)
        if velocity_dict.get('world_ekf_credible'):
            self.length += speed * 0.1
            self.width += speed * 0.01


'''
"mod_3d": {
    "category": "car",
    "sub_category": 0,
    "score": 0.5672,
    "track_id": 1,
    "source_id": 16,
    "is_low_score": 0,
    "detection_box_info": {
        "x": 25.98752,
        "y": -7.36434,
        "z": 0.88943,
        "length": 4.50634,
        "width": 1.79721,
        "height": 1.50453,
        "yaw": -0.4541871282971317,
        "pitch": 0,
        "roll": 0,
        "quaternion": {
            "x": 0.0,
            "y": 0.0,
            "z": -0.22514666569711114,
            "w": 0.9743248836632847
        }
    },
    "autolabel_box_info": {
        "x": 26.01822,
        "y": -7.36004,
        "z": 0.98223,
        "length": 4.51465,
        "width": 1.799,
        "height": 1.52551,
        "yaw": -0.43369674985381645,
        "pitch": 0,
        "roll": 0,
        "quaternion": {
            "x": 0.0,
            "y": 0.0,
            "z": -0.22514666569711114,
            "w": 0.9743248836632847
        },
        "tags": [],
        "yaw_credible": false,
        "credible": true
    },
    "velocity": {
        "world_ekf_credible": true,
        "world_ekf": {
            "x": 6.669848408178496,
            "y": 5.212756196499842,
            "z": 0.0,
            "acc_x": 0.0,
            "acc_y": 0.0,
            "acc_z": 0.0
        },
        "rig": {
            "x": -0.034796156021318594,
            "y": -0.08482152910841959,
            "z": 0.0,
            "acc_x": -0.0023348371748031713,
            "acc_y": -0.0010604713852215703,
            "acc_z": 0.0
        },
        "credible": true,
        "world_formula": {
            "x": 8.148768048392522,
            "y": 5.921750548475401,
            "z": -0.24596480530419257,
            "acc_x": 0.0,
            "acc_y": 0.0,
            "acc_z": 0.0
        }
    },
    "track_state": 3,
}
'''
class Mod3D:
    def __init__(self, mod3d_dict:dict):
        self.track_id = int(0)
        self.category = ""
        self.score = 0.0
        self.bbox3d_info = None
        self.velocity_info = None
        self.velocity = np.array([0, 0, 0])
        self.vel_credible = False
        if mod3d_dict:
            self.parse_mod3d(mod3d_dict)
        self.bbox4d = BBox4D(self.bbox3d_info, self.velocity_info)

    def parse_mod3d(self, mod3d_dict:dict):
        self.track_id = mod3d_dict.get('track_id')
        self.category = mod3d_dict.get('category')
        self.score = mod3d_dict.get('score')
        self.bbox3d_info = mod3d_dict['autolabel_box_info']
        if not self.bbox3d_info:
            self.bbox3d_info = mod3d_dict['detection_box_info']
        self.velocity_info = mod3d_dict.get('velocity')
        if self.velocity_info:
            velocity = self.velocity_info.get('world_ekf')
            self.velocity = np.array([velocity['x'], velocity['y'], velocity['z']])
            self.vel_credible = self.velocity_info.get('world_ekf_credible')

    def get_mod_point_indices(self, points:np.ndarray, kdtree:cKDTree):
        return self.bbox4d.get_inner_point_indices(points, kdtree)

    @staticmethod
    def get_ego_mod3d_dict():
        ego_mod = {
            "category": "car",
            "sub_category": 0,
            "score": 1,
            "track_id": 0,
            "source_id": 0,
            "is_low_score": 0,
            "autolabel_box_info": {
                "x": 1.5,
                "y": 0,
                "z": 1.0,
                "length": 5,
                "width": 2,
                "height": 2,
                "yaw": 0,
                "pitch": 0,
                "roll": 0,
                "quaternion": {
                    "x": 0.0,
                    "y": 0.0,
                    "z": 0.0,
                    "w": 1.0
                },
                "tags": [],
                "yaw_credible": True,
                "credible": True
            },
            "velocity": {
                "world_ekf_credible": False,
                "world_ekf": {
                    "x": 10,
                    "y": 0,
                    "z": 0,
                    "acc_x": 0,
                    "acc_y": 0,
                    "acc_z": 0
                },
            },
            "track_state": 3,
        }
        return ego_mod

'''
"mod_2d": {
    "visible_cams": [
        "cam2",
        "cam4"
    ],
    "cam2": {
        "category": "suv",
        "xmin": 2385.0,
        "ymin": 1320.0,
        "xmax": 2562.0,
        "ymax": 1442.0,
        "MCDO": true,
        "moc_cropped": false,
        "moc_occluded": false,
        "track_id": 2001,
        "source_ids": 3.0,
        "xyz_pred": [],
        "score": 1.0,
        "depth": 24.033313955130296
    },
    "cam4": {
        "category": "sedan",
        "xmin": 234.0,
        "ymin": 689.0,
        "xmax": 343.0,
        "ymax": 761.0,
        "MCDO": false,
        "moc_cropped": false,
        "moc_occluded": false,
        "track_id": 4070,
        "source_ids": 3.0,
        "xyz_pred": [],
        "score": 1.0,
        "depth": 20.248406281774116
    }
}
'''
class Mod2D:
    def __init__(self, mod2d_dict:dict):
        self.visible_cams = []
        self.detections = {}
        if mod2d_dict:
            self.parse_mod2d(mod2d_dict)

    def parse_mod2d(self, mod2d_dict:dict):
        self.visible_cams = mod2d_dict.get('visible_cams')
        for cam_name in self.visible_cams:
            detection_dict = mod2d_dict.get(cam_name)
            self.detections[cam_name] = self.parse_detection(detection_dict)

    def parse_detection(self, detection_dict:dict):
        return Detection2D(detection_dict)

'''
{
    "category": "suv",
    "xmin": 2385.0,
    "ymin": 1320.0,
    "xmax": 2562.0,
    "ymax": 1442.0,
    "MCDO": true,
    "moc_cropped": false,
    "moc_occluded": false,
    "track_id": 2001,
    "source_ids": 3.0,
    "xyz_pred": [],
    "score": 1.0,
    "depth": 24.033313955130296
}
'''
class Detection2D:
    def __init__(self, detection_dict:dict):
        self.category = ""
        self.track_id = 0
        self.score = 0.0
        self.bbox2d = [0, 0, 0, 0]
        if detection_dict:
            self.parse_detection(detection_dict)

    def parse_detection(self, detection_dict:dict):
        self.category = detection_dict.get('category')
        self.track_id = detection_dict.get('track_id')
        self.score = detection_dict.get('score')
        self.bbox2d = [int(detection_dict['xmin']), int(detection_dict['ymin']), int(detection_dict['xmax']), int(detection_dict['ymax'])]
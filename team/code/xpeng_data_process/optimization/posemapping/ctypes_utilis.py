import ctypes
from ctypes import c_char_p, POINTER, Structure, c_bool, c_int, c_double, c_uint64

'''Pixel coordinates on the image'''
class CPoint(Structure):
    _fields_ = [
        ("x", c_double),
        ("y", c_double)
    ]

'''Image data structure'''
class CImage(Structure):
    _fields_ = [
        ("camera_name", c_char_p),
        ("time", c_uint64),
        ("num_points", c_uint64),
        ("points_undistorted", POINTER(CPoint))
    ]

'''Cloud data structure'''
class CCloud(Structure):
    _fields_ = [
        ("cloud_index", c_int),
        ("lidar_name", c_char_p),
        ("time", c_uint64)
    ]

'''Convert image data to ctypes'''
def convert_image_to_ctypes(data):
    num_points = len(data['points_undistorted'])
    PointArrayType = CPoint * num_points
    points_array = PointArrayType()
    for i, point in enumerate(data['points_undistorted']):
        points_array[i] = CPoint(point[0], point[1])
    image_data = CImage(
        camera_name=data['camera_name'].encode('utf-8'),
        time=data['time'],
        num_points=num_points,
        points_undistorted=ctypes.cast(points_array, POINTER(CPoint))
    )
    return image_data

'''Convert image data from ctypes'''
def convert_image_from_ctypes(data):
    data = {
        'camera_name': data.camera_name.decode('utf-8'),
        'time': data.time,
        'points_undistorted': [
            [data.points_undistorted[i].x, data.points_undistorted[i].y]
            for i in range(data.num_points)
        ]
    }
    return data

'''Convert cloud data to ctypes'''
def convert_cloud_to_ctypes(data):
    cloud_data = CCloud(
        cloud_index=data['cloud_index'],
        lidar_name=data['lidar_name'].encode('utf-8'),
        time=data['time']
    )
    return cloud_data

'''Convert cloud data from ctypes'''
def convert_cloud_from_ctypes(data):
    data = {
        'cloud_index': data.cloud_index,
        'lidar_name': data.lidar_name.decode('utf-8'),
        'time': data.time
    }
    return data

'''Convert list of image data to ctypes'''
def convert_images_to_ctypes(data_list):
    ImageDataArrayType = CImage * len(data_list)
    image_data_array = ImageDataArrayType()
    for i, data in enumerate(data_list):
        image_data_array[i] = convert_image_to_ctypes(data)
    return image_data_array

'''Convert list of image data from ctypes'''
def convert_images_from_ctypes(image_data_array, num_images):
    data_list = []
    for i in range(num_images):
        data = {
            'camera_name': image_data_array[i].camera_name.decode('utf-8'),
            'time': image_data_array[i].time,
            'points_undistorted': [
                [image_data_array[i].points_undistorted[j].x, image_data_array[i].points_undistorted[j].y]
                for j in range(image_data_array[i].num_points)
            ]
        }
        data_list.append(data)
    return data_list

'''Convert list of cloud data to ctypes'''
def convert_clouds_to_ctypes(data_list):
    CloudDataArrayType = CCloud * len(data_list)
    cloud_data_array = CloudDataArrayType()
    for i, data in enumerate(data_list):
        cloud_data_array[i] = convert_cloud_to_ctypes(data)
    return cloud_data_array

'''Convert list of cloud data from ctypes'''
def convert_clouds_from_ctypes(cloud_data_array, num_clouds):
    data_list = []
    for i in range(num_clouds):
        data = {
            'cloud_index': cloud_data_array[i].cloud_index,
            'lidar_name': cloud_data_array[i].lidar_name.decode('utf-8'),
            'time': cloud_data_array[i].time
        }
        data_list.append(data)
    return data_list

'''3D landmark point data structure'''
class CLandmark(Structure):
    _fields_ = [
        ("index", c_int),
        ("valid", c_bool),
        ("point3d", c_double * 3)
    ]

'''Convert landmarks data to ctypes'''
def convert_landmarks_to_ctypes(landmarks_data):
    LandmarkArrayType = CLandmark * len(landmarks_data)
    landmarks_array = LandmarkArrayType(
        *(CLandmark(
            index=lm['index'],
            valid=lm['valid'],
            point3d=(ctypes.c_double * 3)(*lm['point3d'])
        ) for lm in landmarks_data)
    )
    return landmarks_array

'''Convert landmarks data from ctypes'''
def convert_landmarks_from_ctypes(landmarks_array, num_landmarks):
    landmarks_data = []
    for i in range(num_landmarks):
        landmark = {
            'index': landmarks_array[i].index,
            'valid': landmarks_array[i].valid,
            'point3d': [landmarks_array[i].point3d[j] for j in range(3)]
        }
        landmarks_data.append(landmark)
    return landmarks_data

'''6DOF Pose data structure'''
class CPose(Structure):
    _fields_ = [
        ("rvec", ctypes.c_double * 3),
        ("tvec", ctypes.c_double * 3),
        ("time", ctypes.c_uint64)
    ]

'''Convert poses data to ctypes'''
def convert_poses_to_ctypes(pose_data_list):
    PoseDataArrayType = CPose * len(pose_data_list)
    pose_data_array = PoseDataArrayType(
        *(CPose(
            rvec=(ctypes.c_double * 3)(*pd['rvec']),
            tvec=(ctypes.c_double * 3)(*pd['tvec']),
            time=pd['time']
        ) for pd in pose_data_list)
    )
    return pose_data_array

'''Convert poses data from ctypes'''
def convert_poses_from_ctypes(pose_data_array, num_poses):
    pose_data_list = []
    for i in range(num_poses):
        pose_data = {
            'rvec': [pose_data_array[i].rvec[j] for j in range(3)],
            'tvec': [pose_data_array[i].tvec[j] for j in range(3)],
            'time': pose_data_array[i].time
        }
        pose_data_list.append(pose_data)
    return pose_data_list

'''KeyPoint data structure'''
class CKeyPoint(Structure):
    _fields_ = [
        ("image_index", c_int),
        ("keypoint_index", c_int),
        ("valid", c_bool)
    ]

'''Visibility data structure'''
class CVisibility(Structure):
    _fields_ = [
        ("landmark_index", c_int),
        ("num_img_kpts", c_int),
        ("img_kpts", POINTER(CKeyPoint))
    ]

'''Create keypoints array from keypoints list'''
def create_keypoints_array(keypoints_list):
    KeyPointArrayType = CKeyPoint * len(keypoints_list)
    keypoints_array = KeyPointArrayType(
        *(CKeyPoint(
            image_index=kp['image_index'],
            keypoint_index=kp['keypoint_index'],
            valid=kp['valid']
        ) for kp in keypoints_list)
    )
    return keypoints_array

'''Create keypoints list from keypoints array'''
def create_keypoints_list(keypoints_array, num_img_kpts):
    keypoints_list = []
    for i in range(num_img_kpts):
        keypoint = {
            'image_index': keypoints_array[i].image_index,
            'keypoint_index': keypoints_array[i].keypoint_index,
            'valid': keypoints_array[i].valid
        }
        keypoints_list.append(keypoint)
    return keypoints_list

'''Convert visibilities data to ctypes'''
def convert_visibilities_to_ctypes(visibilities_data):
    visibility_list = []
    for visibility_data in visibilities_data:
        keypoints_array = create_keypoints_array(visibility_data['img_kpts'])
        visibility = CVisibility(
            landmark_index=visibility_data['landmark_index'],
            num_img_kpts=len(visibility_data['img_kpts']),
            img_kpts=keypoints_array
        )
        visibility_list.append(visibility)
    VisibilityArrayType = CVisibility * len(visibility_list)
    visibilities_array = VisibilityArrayType(*visibility_list)
    return visibilities_array

'''Convert visibilities data from ctypes'''
def convert_visibilities_from_ctypes(visibilities_array, num_visibilities):
    visibilities_data = []
    for i in range(num_visibilities):
        keypoints_list = create_keypoints_list(visibilities_array[i].img_kpts, visibilities_array[i].num_img_kpts)
        visibility_data = {
            'landmark_index': visibilities_array[i].landmark_index,
            'img_kpts': keypoints_list
        }
        visibilities_data.append(visibility_data)
    return visibilities_data

'''Camera intrinsic data structure'''
class CIntrinsic(Structure):
    _fields_ = [
        ("data", c_double * 9)
    ]

'''Camera extrinsic data structure'''
class CExtrinsic(Structure):
    _fields_ = [
        ("rvec", c_double * 3),
        ("tvec", c_double * 3)
    ]

'''Camera data structure'''
class CCamera(Structure):
    _fields_ = [
        ("camera_name", c_char_p),
        ("intrinsic", CIntrinsic),
        ("extrinsic", CExtrinsic)
    ]

'''Lidar data structure'''
class CLidar(Structure):
    _fields_ = [
        ("lidar_name", c_char_p),
        ("extrinsic", CExtrinsic)
    ]

'''Convert camera data to ctypes'''
def convert_cameras_to_ctypes(camera_data_list):
    camera_array_type = CCamera * len(camera_data_list)
    camera_array = camera_array_type(
        *[CCamera(
            camera_name=cam_data['camera_name'].encode('utf-8'),
            intrinsic=CIntrinsic((c_double * 9)(*[elem for row in cam_data['intrinsic'] for elem in row])),
            extrinsic=CExtrinsic(
                (c_double * 3)(*cam_data['extrinsic']['rvec']),
                (c_double * 3)(*cam_data['extrinsic']['tvec'])
            )
        ) for cam_data in camera_data_list]
    )
    return camera_array

'''Convert camera data from ctypes'''
def convert_cameras_from_ctypes(camera_array, num_cameras):
    camera_data_list = []
    for i in range(num_cameras):
        camera_data = {
            'camera_name': camera_array[i].camera_name.decode('utf-8'),
            'intrinsic': [
                [camera_array[i].intrinsic.data[j] for j in range(3)],
                [camera_array[i].intrinsic.data[j] for j in range(3, 6)],
                [camera_array[i].intrinsic.data[j] for j in range(6, 9)]
            ],
            'extrinsic': {
                'rvec': [camera_array[i].extrinsic.rvec[j] for j in range(3)],
                'tvec': [camera_array[i].extrinsic.tvec[j] for j in range(3)]
            }
        }
        camera_data_list.append(camera_data)
    return camera_data_list

'''Convert lidar data to ctypes'''
def convert_lidars_to_ctypes(lidar_data_list):
    lidar_array_type = CLidar * len(lidar_data_list)
    lidar_array = lidar_array_type(
        *[CLidar(
            lidar_name=lidar_data['lidar_name'].encode('utf-8'),
            extrinsic=CExtrinsic(
                (c_double * 3)(*lidar_data['extrinsic']['rvec']),
                (c_double * 3)(*lidar_data['extrinsic']['tvec'])
            )
        ) for lidar_data in lidar_data_list]
    )
    return lidar_array

'''Convert lidar data from ctypes'''
def convert_lidars_from_ctypes(lidar_array, num_lidars):
    lidar_data_list = []
    for i in range(num_lidars):
        lidar_data = {
            'lidar_name': lidar_array[i].lidar_name.decode('utf-8'),
            'extrinsic': {
                'rvec': [lidar_array[i].extrinsic.rvec[j] for j in range(3)],
                'tvec': [lidar_array[i].extrinsic.tvec[j] for j in range(3)]
            }
        }
        lidar_data_list.append(lidar_data)
    return lidar_data_list

'''Map point data structure'''
class CMapPoint(Structure):
    _fields_ = [
        ("cloud_index", c_int),
        ("point3d", c_double * 3),
    ]

'''Map surfel data structure'''
class CMapSurfel(Structure):
    _fields_ = [
        ("cloud_index", c_int),
        ("point3d", c_double * 3),
        ("normal3d", c_double * 3),
        ("point_type", c_int)
    ]

'''Point match data structure'''
class CPointMatch(Structure):
    _fields_ = [
        ("src_point", CMapPoint),
        ("dst_surfel", CMapSurfel),
        ("valid", c_bool)
    ]

'''Cross match data structure'''
class CCrossMatch(Structure):
    _fields_ = [
        ("landmark_index", c_int),
        ("dst_surfel", CMapSurfel),
        ("valid", c_bool)
    ]

'''Convert point matches data to ctypes'''
def convert_point_matches_to_ctypes(point_match_data_list:list):
    point_match_array_type = CPointMatch * len(point_match_data_list)
    point_match_array = point_match_array_type(
        *[CPointMatch(
            src_point=CMapPoint(
                cloud_index=pm['src_point']['cloud_index'],
                point3d=(c_double * 3)(*pm['src_point']['point3d'])
            ),
            dst_surfel=CMapSurfel(
                cloud_index=pm['dst_surfel']['cloud_index'],
                point3d=(c_double * 3)(*pm['dst_surfel']['point3d']),
                normal3d=(c_double * 3)(*pm['dst_surfel']['normal3d']),
                point_type=pm['dst_surfel']['point_type']
            ),
            valid=pm['valid']
        ) for pm in point_match_data_list]
    )
    return point_match_array

'''Convert point matches data from ctypes'''
def convert_point_matches_from_ctypes(point_match_array, num_point_matches):
    point_match_data_list = []
    for i in range(num_point_matches):
        point_match_data = {
            'src_point': {
                'cloud_index': point_match_array[i].src_point.cloud_index,
                'point3d': [point_match_array[i].src_point.point3d[j] for j in range(3)]
            },
            'dst_surfel': {
                'cloud_index': point_match_array[i].dst_surfel.cloud_index,
                'point3d': [point_match_array[i].dst_surfel.point3d[j] for j in range(3)],
                'normal3d': [point_match_array[i].dst_surfel.normal3d[j] for j in range(3)],
                'point_type': point_match_array[i].dst_surfel.point_type
            },
            'valid': point_match_array[i].valid
        }
        point_match_data_list.append(point_match_data)
    return point_match_data_list

'''Convert cross matches data to ctypes'''
def convert_cross_matches_to_ctypes(cross_match_data_list:list):
    cross_match_array_type = CCrossMatch * len(cross_match_data_list)
    cross_match_array = cross_match_array_type(
        *[CCrossMatch(
            landmark_index=pm['landmark_index'],
            dst_surfel=CMapSurfel(
                cloud_index=pm['dst_surfel']['cloud_index'],
                point3d=(c_double * 3)(*pm['dst_surfel']['point3d']),
                normal3d=(c_double * 3)(*pm['dst_surfel']['normal3d']),
                point_type=pm['dst_surfel']['point_type']
            ),
            valid=pm['valid']
        ) for pm in cross_match_data_list]
    )
    return cross_match_array

'''Convert cross matches data from ctypes'''
def convert_cross_matches_from_ctypes(cross_match_array, num_cross_matches):
    cross_match_data_list = []
    for i in range(num_cross_matches):
        cross_match_data = {
            'landmark_index': cross_match_array[i].landmark_index,
            'dst_surfel': {
                'cloud_index': cross_match_array[i].dst_surfel.cloud_index,
                'point3d': [cross_match_array[i].dst_surfel.point3d[j] for j in range(3)],
                'normal3d': [cross_match_array[i].dst_surfel.normal3d[j] for j in range(3)],
                'point_type': cross_match_array[i].dst_surfel.point_type
            },
            'valid': cross_match_array[i].valid
        }
        cross_match_data_list.append(cross_match_data)
    return cross_match_data_list

'''Dataset data structure'''
class CDataset(Structure):
    _fields_ = [
        ("main_sensor", c_char_p),
        ("images", POINTER(CImage)),
        ("landmarks", POINTER(CLandmark)),
        ("poses", POINTER(CPose)),
        ("visibilities", POINTER(CVisibility)),
        ("cameras", POINTER(CCamera)),
        ("lidars", POINTER(CLidar)),
        ("point_matches", POINTER(CPointMatch)),
        ("cross_matches", POINTER(CCrossMatch)),
        ("clouds", POINTER(CCloud)),
        ("time_delay", c_double)
    ]

'''Dataset data structure with number of elements'''
class CDatasetNums(Structure):
    _fields_ = [
        ("num_images", c_int),
        ("num_landmarks", c_int),
        ("num_poses", c_int),
        ("num_visibilities", c_int),
        ("num_cameras", c_int),
        ("num_lidars", c_int),
        ("num_point_matches", c_int),
        ("num_cross_matches", c_int),
        ("num_clouds", c_int),
    ]


if __name__ == '__main__':
    data_list = [
        {
            'camera_name': 'cam2',
            'time': 1673195284742401792,
            'points_undistorted': [
                [857.9024047851562, 1336.4898681640625],
                [1204.8282470703125, 1319.7369384765625]
            ]
        },
        {
            'camera_name': 'cam3',
            'time': 1673195284742401793,
            'points_undistorted': [
                [1107.47265625, 1342.04833984375],
                [947.9561767578125, 1281.47802734375],
                [1207.47265625, 1342.04833984375]
            ]
        }
    ]

    ctypes_data_array = convert_images_to_ctypes(data_list)

    for camera_data in ctypes_data_array:
        print(f"Camera Name: {camera_data.camera_name.decode('utf-8')}")
        print(f"Time: {camera_data.time}")
        print(f"Number of Points: {camera_data.num_points}")
        for i in range(camera_data.num_points):
            print(f"CKeyPoint {i+1}: {camera_data.points_undistorted[i].x}, {camera_data.points_undistorted[i].y}")
        print()

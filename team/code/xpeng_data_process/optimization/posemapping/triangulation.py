import numpy as np
from numba import typed, njit

from .pose import Pose
from .sensor import Landmark, Visibility
from .utils import normalize_point
from .vehicle import Vehicle


'''Compute the skew-symmetric matrix of a vector'''
def skew_symmetric(v:np.ndarray)->np.ndarray:
    # get the vector components
    xyz = v.flatten()
    # get the x, y, and z components
    x = xyz[0]
    y = xyz[1]
    z = xyz[2]
    # create the skew-symmetric matrix
    m = np.array([[0., -z, y], [z, 0., -x], [-y, x, 0.]])
    # return the skew-symmetric matrix
    return m


'''Triangulation class for triangulating 3D points from 2D projections'''
class Triangulation:
    def __init__(self):
        self.projections = [] # list of (camera_matrix, pose_image_world, projection)
        self.A = None # matrix A in Ax = b
        self.b = None # vector b in Ax = b

    '''Compute the error of the triangulation'''
    def compute_error(self, Pw:np.ndarray)->np.ndarray:
        # Pw: 3x1 matrix
        # return: list of errors
        errors = np.asarray(len(self.projections) * [0.0])
        # get all poses in the projections
        #transs = [proj[3] for proj in self.projections]
        # calculate the almost max baseline
        #almost_max_baseline = self.calc_almost_max_baseline(transs)
        # iterate through all projections
        for i, (camera_matrix, pose_image_world, projection) in enumerate(self.projections):
            # transform the 3D point to the camera coordinate
            Pc = pose_image_world.transform_point(Pw)
            # check if the point is in front of the camera and within a reasonable range
            if Pc[2][0] <= 0.2 or Pc[2][0] > 300:
                errors[0] = 1e6
                break
            # project the 3D point to the image plane
            Pc /= Pc[2][0]
            # project the 3D point from the image plane to the pixel plane
            Puv = camera_matrix @ Pc
            # compute the error
            Euv = Puv[:2,0] - projection[:2]
            # compute the squared error
            error = Euv.dot(Euv)
            # append the error to the list
            errors[i] = error
        # return the np array of errors
        return errors

    '''Triangulate the 3D point from the projections'''
    def triangulate(self)->tuple:
        # get the number of projections
        number_projections = len(self.projections)
        # if there are less than 2 projections, return a zero point
        if number_projections <= 2:
            return np.zeros((3, 1)), [1e6]

        # create the matrix A and vector b in Ax = b
        self.A = np.zeros((number_projections * 2, 3))
        self.b = np.zeros((number_projections * 2, 1))

        index = 0
        # iterate through all projections
        for i, (camera_matrix, pose_image_world, projection) in enumerate(self.projections):
            # calculate the index for the matrix A and vector b
            index = i*2
            # compute the equation for the projection
            A, b = self._compute_equation(camera_matrix, pose_image_world, projection)
            # add the equation to the matrix A and vector b
            self.A[index:index+2, :] = A[0:2, :]
            self.b[index:index+2] = b[0:2]
        # solve the linear system
        point3d_estimated = np.linalg.lstsq(self.A, self.b, rcond=None)[0]
        # compute the error
        errors = self.compute_error(point3d_estimated)
        # return the estimated 3D point and errors
        return point3d_estimated, errors

    '''Compute the equation for the projection'''
    def _compute_equation(self, camera_matrix:np.ndarray, pose_image_world:np.ndarray, projection:np.ndarray):
        # camera_matrix: 3x3 matrix
        # pose_image_world: Pose object
        # projection: 2x1 matrix
        # return: A matrix and b vector
        # alias the camera matrix
        K = camera_matrix
        # get the rotation and translation from the world to the image
        R = pose_image_world.R
        t = pose_image_world.t
        # compute the projection matrix
        Puv = np.array([[projection[0]], [projection[1]], [1]])
        # compute the 3D point in the camera coordinate
        Pc = np.matmul(np.linalg.inv(K), Puv)
        # compute the skew-symmetric matrix of the 3D point
        Pcx = skew_symmetric(Pc)
        # compute the matrix A and vector b
        A = np.matmul(-Pcx, R)
        # compute the vector b
        b = np.matmul(Pcx, t)
        # return the matrix A and vector b
        return A, b


'''Triangulator class for triangulating 3D points from a list of image keypoints'''
class Triangulator:
    def __init__(self, vehicle:Vehicle):
        self.vehicle = vehicle # vehicle object
        self.sigma_square = 100.0 # sigma square for the error threshold

    '''Triangulate the 3D point from a list of image keypoints'''
    def triangulate_keypoints(self, img_kpts:list):
        # img_kpts: list of ImageKeyPoint objects
        # return: 3D point
        # Create a triangulation object
        triangulation = Triangulation()
        # Iterate through all image keypoints
        for img_kpt in img_kpts:
            # Get the image index and keypoint index
            image_index = img_kpt.image_index
            keypoint_index = img_kpt.keypoint_index
            # Get the image, pose, and camera
            image = self.vehicle.get_image_by_index(image_index)
            camera = self.vehicle.get_image_camera(image)
            # Get the intrinsic matrix
            intrinsic = camera.intrinsic
            # Get the transformation from the world to the image
            pose_image_world = self.vehicle.get_image_pose_inv(image)
            # Get the undistorted keypoint
            kpt_un = image.keypoints_undistorted[keypoint_index]
            # Add the projection to the triangulation
            triangulation.projections.append((intrinsic, pose_image_world, kpt_un.pt))
        # Triangulate the 3D point
        point3d_estimated, errors = triangulation.triangulate()
        # Check if the errors is valid
        if errors[0] >= 1e6:
            return None
        # Check if the point is valid
        valid_cnt = np.sum(errors < 5.991 * self.sigma_square)
        # # Iterate through all errors
        # for i in range(len(errors)):
        #     # Check if the error is greater than the threshold
        #     if errors[i] > 5.991 * self.sigma_square:
        #         # Set the keypoint to invalid
        #         img_kpts[i].valid = False
        #     # Otherwise, increment the valid count
        #     else:
        #     # Increment the valid count
        #         valid_cnt += 1
        # Check if the valid observation is less than 2
        if valid_cnt <= 2:
            # Return None if the valid observation is less than 2
            return None
        # Return the estimated 3D point
        return point3d_estimated.T[0]


'''Test the triangulation'''
def test_triangulation():
    point3d = np.array([2,1,4]).reshape((3,1))
    pose1 = Pose.identity()
    pose2 = Pose.from_pose_vector(np.array([0,0.1,0,1,0,0]))
    pose3 = Pose.from_pose_vector(np.array([0.1,0,0,0,1,0]))
    fx, fy, cx, cy = 1000, 1000, 1024, 768
    intrinsic = np.array([[fx,0,cx],[0,fy,cy],[0,0,1]])
    proj3d_1 = intrinsic @ pose1.transform_point(point3d)
    proj3d_2 = intrinsic @ pose2.transform_point(point3d)
    proj3d_3 = intrinsic @ pose3.transform_point(point3d)
    proj2d_1 = normalize_point(proj3d_1)[:2].reshape((2,))
    proj2d_2 = normalize_point(proj3d_2)[:2].reshape((2,))
    proj2d_3 = normalize_point(proj3d_3)[:2].reshape((2,))

    triangulation = Triangulation()
    triangulation.projections.append((intrinsic, pose1, proj2d_1, pose1.t))
    triangulation.projections.append((intrinsic, pose2, proj2d_2, pose2.t))
    triangulation.projections.append((intrinsic, pose3, proj2d_3, pose3.t))
    point3d_estimated, res, rank, sigulars = triangulation.triangulate()
    print(point3d_estimated)
    error = triangulation.compute_error(point3d_estimated)
    print(error)

def convert_datatype(chains, vehicle):
    pose_image_world_list = typed.List()
    kpt_all_list = typed.List()
    camera_name_list = typed.List()
    for image in vehicle.image_list:
        camera_name_list.append(image.camera_name)
        pose_image_world = vehicle.get_image_pose_inv(image)
        pose_image_world_list.append(pose_image_world.get_transform_matrix())
        kpt_tmp_list = [[kpt.pt[0], kpt.pt[1]] for kpt in image.keypoints_undistorted]
        if len(image.keypoints_undistorted) == 0:
            kpt_tmp_list = [[0, 0]]
        kpt_tmp_list = np.asarray(kpt_tmp_list, dtype=np.float64)
        kpt_all_list.append(kpt_tmp_list)

    intrinsic_dict = typed.Dict()
    for i in range(len(vehicle.camera_list)):
        camera = vehicle.camera_list[i]
        intrinsic_dict[camera.camera_name] = camera.intrinsic

    kpt_index_list = typed.List()
    for img_kpts in chains:
        kpt_index_tmp_list = [[ik.image_index, ik.keypoint_index] for ik in img_kpts]
        kpt_index_tmp_list = np.asarray(kpt_index_tmp_list, dtype=np.int64)
        kpt_index_list.append(kpt_index_tmp_list)

    return pose_image_world_list, kpt_all_list, kpt_index_list, camera_name_list, intrinsic_dict

@njit
def skew_symmetric_numba(v):
    xyz = v.flatten()
    x = xyz[0]
    y = xyz[1]
    z = xyz[2]
    m = np.array([[0., -z, y], [z, 0., -x], [-y, x, 0.]])
    return m

@njit
def _compute_equation_numba(camera_matrix, pose_image_world, projection):
    K = camera_matrix
    R = pose_image_world[:3, :3]
    R_c = np.ascontiguousarray(R)
    t = pose_image_world[:3, 3]
    t_c = np.ascontiguousarray(t)
    Puv = np.array([projection[0], projection[1], 1])
    Ki = np.linalg.inv(K)
    Ki_c = np.ascontiguousarray(Ki)
    Puv_c = np.ascontiguousarray(Puv)
    Pc = np.dot(Ki_c, Puv_c)
    Pcx = skew_symmetric_numba(Pc)
    Pcx_c = np.ascontiguousarray(Pcx)
    AA = -np.dot(Pcx_c, R_c)
    bb = np.dot(Pcx_c, t_c)
    return AA, bb

@njit
def compute_error_numba(projection_intrinsic_list, projection_pose_image_world_list, projection_kpt_un_list, Pw):
    errors = np.zeros(len(projection_intrinsic_list), dtype=np.float64)
    for i in range(len(projection_intrinsic_list)):
        K = projection_intrinsic_list[i]
        K_c = np.ascontiguousarray(K)
        Tiw = projection_pose_image_world_list[i]
        Tiw_c = np.ascontiguousarray(Tiw)
        Pw_c = np.ascontiguousarray(Pw)
        #projection = np.asarray(projection_kpt_un_list[i], dtype=np.float64)
        Pc = np.dot(Tiw_c, Pw_c)
        if Pc[2][0] <= 0.2 or Pc[2][0] > 300:
            errors[0] = 1e6
            break
        Pc /= Pc[2][0]
        P = Pc[:3, 0]
        P_c = np.ascontiguousarray(P)
        Puv = np.dot(K_c, P_c)
        Euv = Puv[:2] - np.asarray(projection_kpt_un_list[i], dtype=np.float64)
        Euv_c = np.ascontiguousarray(Euv)
        error = np.dot(Euv_c, Euv_c)
        errors[i] = error
    return errors

@njit
def trangulate_numba(projection_intrinsic_list, projection_pose_image_world_list, projection_kpt_un_list):
    number_projections = len(projection_intrinsic_list)
    if number_projections <= 2:
        return np.zeros((3, 1), dtype=np.float64), np.ones(1) * 1e6
    res_A = np.zeros((number_projections * 2, 3), dtype=np.float64)
    res_b = np.zeros((number_projections * 2, 1), dtype=np.float64)
    index = 0
    for i in range(len(projection_pose_image_world_list)):
        camera_matrix = projection_intrinsic_list[i]
        pose_image_world = projection_pose_image_world_list[i]
        projection = np.asarray(projection_kpt_un_list[i], dtype=np.float64)
        index = i*2
        A, b = _compute_equation_numba(camera_matrix, pose_image_world, projection)
        res_A[index:index+2, :] = A[0:2, :]
        res_b[index:index+2] = b[0:2][:, None]
    point3d_estimated = np.linalg.lstsq(res_A, res_b)[0]
    point3d_estimated = np.vstack((point3d_estimated, np.ones((1, 1), dtype=np.float64)))
    errors = compute_error_numba(projection_intrinsic_list, projection_pose_image_world_list, projection_kpt_un_list, point3d_estimated)
    return point3d_estimated, errors

def get_landmarks(point3d_estimated):
    if (point3d_estimated == np.zeros(3)).all():
        return None
    landmark = Landmark(0, point3d_estimated)
    return landmark

def triangulate_points_process(chains, vehicle):
    pose_image_world_list, kpt_all_list, kpt_index_list, camera_name_list, intrinsic_dict = \
         convert_datatype(chains, vehicle)
    sigma_square = 100.0

    point3d_estimateds = triangulate_points_numba(pose_image_world_list, kpt_all_list, kpt_index_list, camera_name_list, intrinsic_dict, sigma_square)

    return point3d_estimateds

@njit
def triangulate_points_numba(pose_image_world_list, kpt_all_list, kpt_index_list, camera_name_list, intrinsic_dict, sigma_square):
    res = np.zeros((len(kpt_index_list), 4), dtype=np.float64)
    for i, kpts_index in enumerate(kpt_index_list):
        projection_intrinsic_list = typed.List()
        projection_pose_image_world_list = typed.List()
        projection_kpt_un_list = typed.List()
        for kpt_index in kpts_index:
            image_index = kpt_index[0]
            keypoint_index = kpt_index[1]
            camera_name = camera_name_list[image_index]
            pose_image_world = pose_image_world_list[image_index]
            intrinsic = intrinsic_dict[camera_name]
            kpt_un = kpt_all_list[image_index][keypoint_index]
            projection_intrinsic_list.append(intrinsic)
            projection_pose_image_world_list.append(pose_image_world)
            projection_kpt_un_list.append(kpt_un)

        point3d_estimated, errors = trangulate_numba(projection_intrinsic_list, projection_pose_image_world_list, projection_kpt_un_list)
        if errors[0] < 1e6 and np.sum(errors < 5.991 * sigma_square) > 2:
            res[i] = point3d_estimated.T
    return res

if __name__ == "__main__":
    test_triangulation()
    print("Done!")
import argparse
import os
import numpy as np
import open3d as o3d
import cv2
from tqdm import tqdm
import json


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--data_root')
    parser.add_argument('--seg_dir')
    parser.add_argument('--cam')
    args = parser.parse_args()

    data_root= args.data_root
    seg_dir= args.seg_dir
    cam= args.cam

    cam2_truncated_height = 792 # 大于cam2_truncated_height 为ego_mask区域

    # ------------------------------------------------------------------------------------
    # 读取lidar外参, 相机内参外参, cam_to_worlds
    transform_json = json.load(open(os.path.join(data_root, "transform.json")))
    ex_lidar_to_ego = transform_json["sensor_params"]["lidar1"]["extrinsic"]

    ex_params_cam = transform_json["sensor_params"][cam]["extrinsic"]
    in_params_cam = transform_json["sensor_params"][cam]["camera_intrinsic"]
    l2c=np.linalg.inv(ex_params_cam) @ ex_lidar_to_ego

    in_params_cam=np.matrix(in_params_cam)
    print('intrinsic:')
    print(in_params_cam)

    localpose = json.load(open(os.path.join(data_root, "localpose.json")))
    actual_timestamps = sorted([int(k) for k in localpose.keys()])
    transform_matrix = {}
    cam_to_worlds = []
    for frame in transform_json["frames"]:
        if frame["camera"]==cam:
            transform_matrix[frame["timestamp"]] = frame["transform_matrix"]
    cam_to_ego = transform_json["sensor_params"][cam]["extrinsic"]
    cam_to_ego_inv = np.linalg.inv(cam_to_ego)
    print('ego to cam:')
    print(cam_to_ego_inv)
    n_pose= len(transform_matrix)
    print(n_pose)

    ego_to_worlds = []
    for t in range(0, n_pose):
        cam_to_worlds.append(transform_matrix[actual_timestamps[t]])
    cam_to_worlds= np.stack(cam_to_worlds, axis=0)
    for cam_to_world in cam_to_worlds:
        ego_to_world = cam_to_world @ cam_to_ego_inv
        ego_to_worlds.append(ego_to_world)
    ego_to_worlds = np.stack(ego_to_worlds, axis=0)
    ego_to_world_start_inv= np.linalg.inv( ego_to_worlds[0])

    pcd_dir=data_root+ '/pcd'
    filenames=sorted((fn for fn in os.listdir(pcd_dir) if fn.endswith('.pcd')))
    pcd_grounds=[]
    colors_grounds=[]
    pcd_ngrounds=[]
    colors_ngrounds=[]
    grd_set = (7, 8, 13, 14, 23, 24, 41, 10, 36, 43)
    dyn_set = [52, 53, 54, 55, 56, 57, 58, 59, 60, 61, 62, 63, 64, 65, 0, 1, 19, 20, 21, 22]

    for t in tqdm(range(len(filenames))):
        fn= filenames[t].split('.')[0]
        pcd = o3d.io.read_point_cloud(pcd_dir+'/'+filenames[t])
        pts = np.asarray(pcd.points).astype(np.float32)
        rot0= np.matrix(ex_lidar_to_ego)[:3,:3]
        t_vect0= np.matrix(ex_lidar_to_ego)[:3,3]
        points= np.matmul(rot0,pts.T)
        lidar_points_ego=points.T+t_vect0.T

        # ------------------------------------------------------------------------------------
        # # 使用delta_lidar2ego变换
        # if apply_delta_lidar2ego:
        #     lidar_points_ego=lidar_points_ego+delta_lidar2ego[:3,3].T
        #     delta_lidar2ego2=np.eye(4)
        #     delta_lidar2ego2[:3,3]=delta_lidar2ego[:3,3]
        #     ex_lidar_to_ego2= delta_lidar2ego2 @ ex_lidar_to_ego
        #     l2c=np.linalg.inv(ex_params_cam) @ ex_lidar_to_ego2

        rot= l2c[:3,:3]
        t_vect=l2c[:3,3]
        points= np.matmul(rot,pts.T)
        lidar_points_cam=points.T+t_vect
        lidar_points_image=np.matmul(in_params_cam,lidar_points_cam.T)
        lidar_points_image=lidar_points_image.T

        depth = lidar_points_image[:, 2]
        cam_points = lidar_points_image[:, :2] / (depth + 1e-6)
        colors = np.zeros((len(depth), 3))

        ground_mask=np.zeros(len(depth))
        seg_mask = cv2.imread(seg_dir+'/'+cam+'/'+fn+'.png', cv2.IMREAD_ANYDEPTH)
        image = cv2.imread(data_root+'/images/'+cam+'/' + fn+'.png')[..., [2, 1, 0]] / 255.

        width=image.shape[1]
        height=image.shape[0]
        if cam== 'cam2':
            truncated_height= cam2_truncated_height
        if cam== 'cam0':
            truncated_height=height-1

        # generate new dynamic mask
        dyn_mask = np.isin(seg_mask, dyn_set).astype(np.uint8) * 255

        # print('valid points: '+str(len(depth)))
        # for u in range(len(depth)):
        #     if (cam_points[u, 0] >= 0)& (cam_points[u, 0] <= (width-1) )& (cam_points[u, 1] >= 0)& (cam_points[u, 1] <= truncated_height): # (1080-1) 792
        #         if (depth[u] > 0) & (depth[u] < 150):
        #             if dyn_mask[round( cam_points[u, 1]), round( cam_points[u, 0])]>0:
        #                 continue

        #             colors[u,:]=image[round( cam_points[u, 1]), round( cam_points[u, 0])]
        #             # if seg_mask[round( cam_points[u, 1]), round( cam_points[u, 0])]>0:
        #             if seg_mask[round( cam_points[u, 1]), round( cam_points[u, 0])] in grd_set:
        #                 ground_mask[u]=1 # road points
        #             else:
        #                 ground_mask[u]=2 # non road points

        # print('road points: '+str(len( ground_mask[ground_mask==1])))
        # print('non road points: '+str(len( ground_mask[ground_mask==2])))

        # rot= ego_to_worlds[t,:3,:3]
        # t_vect=ego_to_worlds[t,:3,3]

        # colors_ground = colors[ground_mask==1,:]
        # colors_nground = colors[ground_mask==2,:]

        # ------------------------------------------------------------------------------------
        # 转化出lidar2cam优化所需点云数据和图像 (去除动态物体后)
        if cam== 'cam0':
            # if t>= num_pcd_cvt:
            #     break
            # points_ground=lidar_points_ego[ground_mask==1,:]
            # refl_ground=colors_ground[:,0]*0.299+colors_ground[:,1]*0.587+colors_ground[:,2]*0.114
            # points_nground=lidar_points_ego[ground_mask==2,:]
            # refl_nground=colors_nground[:,0]*0.299+colors_nground[:,1]*0.587+colors_nground[:,2]*0.114

            # points_frame= np.concatenate([points_ground, points_nground], axis=0)
            # colors_frame=np.concatenate([refl_ground, refl_nground], axis=0).reshape(-1,1)
            # pcd_frame= np.concatenate([points_frame, colors_frame], axis=1)
            # np.savetxt(data_root+'/dyn_mask/'+ str(t).zfill(2)+ '.txt', pcd_frame, delimiter=' ')

            image1 = cv2.imread(data_root+'/images/'+cam+'/' + fn+'.png')
            mask=(dyn_mask>0)
            image1[mask,:]=0
            # width1=image1.shape[1]
            # height1=image1.shape[0]

            # cv2.imwrite(data_root+'/dyn_mask/' +str(t).zfill(2)+'.png', cv2.resize(image1, (round(width1*0.5), round(height1*0.5))))
            # cv2.imwrite(data_root+'/dyn_mask/' +str(t).zfill(2)+'.png', image1)
            cv2.imwrite(data_root+'/dyn_mask/' + fn +'.png', image1)

            # image2 = cv2.imread(data_root+'/images/'+cam+'/' + fn+'.png')
            # mask2=(grd_mask==1)
            # image2[mask2,:]=0
            # cv2.imwrite(data_root+'/dyn_mask/' +str(t).zfill(2)+'_grd.png', image2)

if __name__ == '__main__':
    main()
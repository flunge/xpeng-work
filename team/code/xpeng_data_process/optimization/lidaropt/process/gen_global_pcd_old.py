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
    parser.add_argument('--dyn_mask_dir')
    parser.add_argument('--road_mask_dir')
    parser.add_argument('--cam')
    parser.add_argument('--num_pcd_cvt')
    parser.add_argument('--apply_delta_lidar2ego', action="store_true")
    args = parser.parse_args()

    data_root= args.data_root
    dyn_mask_dir= args.dyn_mask_dir
    road_mask_dir= args.road_mask_dir
    cam= args.cam
    num_pcd_cvt=int(args.num_pcd_cvt) # 50
    apply_delta_lidar2ego=False
    if args.apply_delta_lidar2ego:
        apply_delta_lidar2ego=True

    cam2_truncated_height= 792 # 大于cam2_truncated_height 为ego_mask区域
    
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
    # print(ego_to_world_start_inv)

    # ------------------------------------------------------------------------------------
    # 读取lidar2cam优化结果
    if apply_delta_lidar2ego:
        l2c_res_json = json.load(open(os.path.join(data_root +'/pcd_cvt_0', "res.json")))
        ext = l2c_res_json["res"]["mat"]
        cam0_to_ego = transform_json["sensor_params"]['cam0']["extrinsic"]
        delta_lidar2ego= np.array(cam0_to_ego) @ ext
        print('delta_lidar2ego:')
        print(delta_lidar2ego)
        delta_lidar2ego2=np.eye(4)
        delta_lidar2ego2[:3,3]=delta_lidar2ego[:3,3]
        # output
        np.savetxt(data_root+'/delta_lidar2ego.txt', delta_lidar2ego, delimiter=' ')
        np.savetxt(data_root+'/delta_lidar2ego2.txt', delta_lidar2ego2, delimiter=' ')
        return

    if cam== 'cam0':
        # ------------------------------------------------------------------------------------
        # 生成lidar2cam优化所需数据 (kitti形式)
        # in_params_cam1 = in_params_cam.copy()
        # in_params_cam1= in_params_cam1*0.5
        # in_params_cam1[2,2] = 1.0
        # print('intrinsic_halfres:')
        # print(in_params_cam1)
        os.makedirs(data_root +'/pcd_cvt_0', exist_ok=True)
        np.savetxt(data_root+'/pcd_cvt_0/LiDAR_poses.txt', ego_to_worlds[:50,:,:].reshape(50,16), delimiter=' ') 
        np.savetxt(data_root+'/pcd_cvt_0/egoposes.txt', ego_to_worlds[:50,:3,:].reshape(50,12), delimiter=' ') 
        # np.savetxt(data_root+'/pcd_cvt_0/'+'intr.txt', in_params_cam1, delimiter=' ')
        np.savetxt(data_root+'/pcd_cvt_0/'+'intr.txt', in_params_cam, delimiter=' ') 
        np.savetxt(data_root+'/pcd_cvt_0/'+'ego2cam.txt', cam_to_ego_inv, delimiter=' ') 

        # calib.txt
        intr1= np.zeros((3, 4))
        # intr1[:3,:3]=in_params_cam1
        intr1[:3,:3]=in_params_cam
        intr1=intr1.reshape(-1)
        e2c1= cam_to_ego_inv[:3,:]
        e2c1=e2c1.reshape(-1)
        fl1 = open(data_root+'/pcd_cvt_0/'+'calib.txt', 'w')
        ls1 ='P0:'
        for it in range(0, 12):
            ls1=ls1+' '+str(intr1[it]) 
        ls1=ls1+'\n'
        fl1.writelines(ls1)
        ls1 ='Tr:'
        for it in range(0, 12):
            ls1=ls1+' '+str(e2c1[it]) 
        ls1=ls1+'\n'
        fl1.writelines(ls1)
        fl1.close()
    
    pcd_dir=data_root+ '/pcd'
    filenames=sorted((fn for fn in os.listdir(pcd_dir) if fn.endswith('.pcd')))
    pcd_grounds=[]
    colors_grounds=[]
    pcd_ngrounds=[]
    colors_ngrounds=[]
    for t in tqdm(range(len(filenames))): 
        fn= filenames[t].split('.')[0]
        pcd = o3d.io.read_point_cloud(pcd_dir+'/'+filenames[t])
        pts = np.asarray(pcd.points).astype(np.float32)
        rot0= np.matrix(ex_lidar_to_ego)[:3,:3]
        t_vect0= np.matrix(ex_lidar_to_ego)[:3,3]
        points= np.matmul(rot0,pts.T)
        lidar_points_ego=points.T+t_vect0.T

        # ------------------------------------------------------------------------------------
        # 使用delta_lidar2ego变换
        if apply_delta_lidar2ego:
            lidar_points_ego=lidar_points_ego+delta_lidar2ego[:3,3].T
            delta_lidar2ego2=np.eye(4)
            delta_lidar2ego2[:3,3]=delta_lidar2ego[:3,3]
            ex_lidar_to_ego2= delta_lidar2ego2 @ ex_lidar_to_ego
            l2c=np.linalg.inv(ex_params_cam) @ ex_lidar_to_ego2

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
        dyn_mask = cv2.imread(dyn_mask_dir+'/'+fn+'.png', cv2.IMREAD_ANYDEPTH)
        road_mask = cv2.imread(road_mask_dir+'/'+fn+'.png', cv2.IMREAD_ANYDEPTH)
        image = cv2.imread(data_root+'/images/'+cam+'/' + fn+'.png')[..., [2, 1, 0]] / 255.
        width=image.shape[1]
        height=image.shape[0]
        if cam== 'cam2':
            truncated_height= cam2_truncated_height 
        if cam== 'cam0':
            truncated_height=height-1
        
        print('valid points: '+str(len(depth)))
        for u in range(len(depth)):
            if (cam_points[u, 0] >= 0)& (cam_points[u, 0] <= (width-1) )& (cam_points[u, 1] >= 0)& (cam_points[u, 1] <= truncated_height): # (1080-1) 792
                if (depth[u] > 0) & (depth[u] < 150):
                    if dyn_mask[round( cam_points[u, 1]), round( cam_points[u, 0])]>0:
                        continue
                    
                    colors[u,:]=image[round( cam_points[u, 1]), round( cam_points[u, 0])]
                    if road_mask[round( cam_points[u, 1]), round( cam_points[u, 0])]>0:
                        ground_mask[u]=1 # road points
                    else:
                        ground_mask[u]=2 # non road points
        
        print('road points: '+str(len( ground_mask[ground_mask==1])))
        print('non road points: '+str(len( ground_mask[ground_mask==2])))
        
        rot= ego_to_worlds[t,:3,:3]
        t_vect=ego_to_worlds[t,:3,3]
        
        colors_ground = colors[ground_mask==1,:]
        colors_nground = colors[ground_mask==2,:]
        
        # ------------------------------------------------------------------------------------
        # ego to world, 多帧叠加
        if cam== 'cam2':
            pts =  lidar_points_ego[ground_mask==1,:]
            points= np.matmul(rot,pts.T)
            points_ground=points.T+t_vect.T

            pts =  lidar_points_ego[ground_mask==2,:]
            points= np.matmul(rot,pts.T)
            points_nground=points.T+t_vect.T
            if t==0:
                pcd_grounds=points_ground
                colors_grounds=colors_ground
                pcd_ngrounds=points_nground
                colors_ngrounds=colors_nground
            else:
                pcd_grounds=np.concatenate([pcd_grounds, points_ground], axis=0)
                colors_grounds=np.concatenate([colors_grounds, colors_ground], axis=0)
                pcd_ngrounds=np.concatenate([pcd_ngrounds, points_nground], axis=0)
                colors_ngrounds=np.concatenate([colors_ngrounds, colors_nground], axis=0)
        
        # ------------------------------------------------------------------------------------
        # 转化出lidar2cam优化所需点云数据和图像 (去除动态物体后)
        if cam== 'cam0':
            if t>= num_pcd_cvt:
                break
            points_ground=lidar_points_ego[ground_mask==1,:]
            refl_ground=colors_ground[:,0]*0.299+colors_ground[:,1]*0.587+colors_ground[:,2]*0.114
            points_nground=lidar_points_ego[ground_mask==2,:]
            refl_nground=colors_nground[:,0]*0.299+colors_nground[:,1]*0.587+colors_nground[:,2]*0.114

            points_frame= np.concatenate([points_ground, points_nground], axis=0)
            colors_frame=np.concatenate([refl_ground, refl_nground], axis=0).reshape(-1,1)
            pcd_frame= np.concatenate([points_frame, colors_frame], axis=1)
            np.savetxt(data_root+'/pcd_cvt_0/'+ str(t).zfill(2)+ '.txt', pcd_frame, delimiter=' ') 

            image1 = cv2.imread(data_root+'/images/'+cam+'/' + fn+'.png')
            mask=(dyn_mask>0) 
            image1[mask,:]=0
            # width1=image1.shape[1]
            # height1=image1.shape[0]

            # cv2.imwrite(data_root+'/pcd_cvt_0/' +str(t).zfill(2)+'.png', cv2.resize(image1, (round(width1*0.5), round(height1*0.5))))
            cv2.imwrite(data_root+'/pcd_cvt_0/' +str(t).zfill(2)+'.png', image1)
    
    # ------------------------------------------------------------------------------------
    # 生成新的整体点云和ground_mask
    if cam== 'cam2':
        pcd_all = o3d.geometry.PointCloud()
        
        # voxel_size= 0.05
        pcd_ground = o3d.geometry.PointCloud()
        pcd_ground.points = o3d.utility.Vector3dVector(np.asarray(pcd_grounds))
        pcd_ground.colors = o3d.utility.Vector3dVector(colors_grounds)
        # pcd_ground = pcd_ground.voxel_down_sample(voxel_size= voxel_size)

        pcd_nground = o3d.geometry.PointCloud()
        pcd_nground.points = o3d.utility.Vector3dVector(np.asarray(pcd_ngrounds)) 
        pcd_nground.colors = o3d.utility.Vector3dVector(colors_ngrounds)
        # pcd_nground = pcd_nground.voxel_down_sample(voxel_size= voxel_size)

        pcd_all=pcd_ground+pcd_nground
        normals_all=np.zeros((len(np.asarray(pcd_all.points)),3))
        pcd_all.normals = o3d.utility.Vector3dVector(normals_all)
        o3d.io.write_point_cloud(data_root +'/points3D_bkgd_new.ply', pcd_all)
        
        mask_ground=np.ones((np.asarray(pcd_ground.points).shape[0],1))
        mask_nground=np.zeros((np.asarray(pcd_nground.points).shape[0],1))
        mask_all=  np.concatenate([mask_ground, mask_nground], axis=0)
        mask_all_bool = mask_all>0
        np.save(data_root+ '/ground_mask_new.npy',mask_all_bool)
        print('all road points: '+str(len(mask_ground)))
        print('all non road points: '+str(len(mask_nground)))

if __name__ == '__main__':
    main()
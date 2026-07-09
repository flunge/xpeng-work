import os
import cv2
from tqdm import tqdm
import numpy as np
import json
from scipy.spatial.transform import Rotation as ScipyRot
import shutil
from ..colmap.scripts.python import read_write_model
from ..utility import colmap_db


def generate_trip_cam_videos():
    """
    Generate a video for each trip in the experiement folder.
    """
    exp_dir = "/workspace/yuhangl@xiaopeng.com/exp_reconstruction/exp_intersection_2_v6"
    img_dir = os.path.join(exp_dir, "image")
    video_dir = os.path.join(exp_dir, "cam_video")
    os.makedirs(video_dir, exist_ok=True)
    h, w = 450, 800
    fourcc = cv2.VideoWriter_fourcc('m', 'p', '4', 'v')
    for vehicle_name in os.listdir(img_dir):
        for trip_name in os.listdir(os.path.join(img_dir, vehicle_name)):
            print(vehicle_name, trip_name)
            os.makedirs(os.path.join(video_dir, vehicle_name), exist_ok=True)
            if trip_name != "1699396984900000000":
                continue
            video = cv2.VideoWriter(os.path.join(video_dir, vehicle_name, f"{trip_name}.mp4"), fourcc=fourcc, fps=20, frameSize=(w*2, h*5))
            num_slice = len(os.listdir(os.path.join(img_dir, vehicle_name, trip_name, "cam0")))
            for slice_idx in tqdm(range(num_slice)):
                # if slice_idx > 10:
                #     continue
                img0 = cv2.imread(os.path.join(img_dir, vehicle_name, trip_name, "cam0", f"slice{slice_idx}.png"))
                img2 = cv2.imread(os.path.join(img_dir, vehicle_name, trip_name, "cam2", f"slice{slice_idx}.png"))
                img3 = cv2.imread(os.path.join(img_dir, vehicle_name, trip_name, "cam3", f"slice{slice_idx}.png"))
                img4 = cv2.imread(os.path.join(img_dir, vehicle_name, trip_name, "cam4", f"slice{slice_idx}.png"))
                img5 = cv2.imread(os.path.join(img_dir, vehicle_name, trip_name, "cam5", f"slice{slice_idx}.png"))
                img6 = cv2.imread(os.path.join(img_dir, vehicle_name, trip_name, "cam6", f"slice{slice_idx}.png"))
                img7 = cv2.imread(os.path.join(img_dir, vehicle_name, trip_name, "cam7", f"slice{slice_idx}.png"))

                concat_img = np.zeros((h*5, w*2, 3), dtype=np.uint8)
                concat_img[0:h, w//2:w//2+w] = cv2.resize(img0, (w, h))
                concat_img[h:2*h, w//2:w//2+w] = cv2.resize(img2, (w, h))
                concat_img[2*h:3*h, 0:w] = cv2.resize(img3, (w, h))
                concat_img[2*h:3*h, w:2*w] = cv2.resize(img4, (w, h))
                concat_img[3*h:4*h, 0:w] = cv2.resize(img5, (w, h))
                concat_img[3*h:4*h, w:2*w] = cv2.resize(img6, (w, h))
                concat_img[4*h:, w//2:w//2+w] = cv2.resize(img7, (w, h))
                # print(concat_img.shape)
                # cv2.imwrite("/workspace/yuhangl@xiaopeng.com/surface_reconstruction/_debug.png", concat_img)
                # exit()
                video.write(concat_img)
            video.release()


def draw_trip_trajectory(ax, trip_idx, trajectory, color):
    """
    Draw the xy trajectory of a trip.
    """
    ax.scatter(trajectory[:, 0], trajectory[:, 1], s=10, color=color, label=trip_idx)
    arrow_start = None
    arrow_end = trajectory[-1]
    for i in range(2, len(trajectory)):
        if np.linalg.norm(trajectory[-i] - arrow_end) > 1:
            arrow_start = trajectory[-i]
            break
    if arrow_start is not None:
        ax.quiver(arrow_end[0], arrow_end[1], arrow_end[0]-arrow_start[0], arrow_end[1]-arrow_start[1], color=color)


def get_outlier_cam_img_idx(trip_path):
    """
    Find the index of outlier cam images in a trip.
    """
    raw_trip_calib = json.load(open(os.path.join(trip_path, "calib.json"), "r"))
    seg_mask_path = trip_path.replace("/image/", "/seg_mask/")
    outlier_cam_list = raw_trip_calib.get("outlier_cam_list", [])
    cam_list = [x for x in os.listdir(seg_mask_path) if "cam" in x]
    cam_list.sort()

    img_paths = []
    idx = 0
    outlier_cam_img_idx = []
    for cam_name in cam_list:
        num_slice = 0
        contents_cam_dir = os.listdir(os.path.join(seg_mask_path, cam_name))
        for item in contents_cam_dir:
            if 'slice' in item:
                num_slice += 1

        for slice_idx in range(num_slice):
            slice_name = f"slice{slice_idx}"
            img_paths.append(os.path.join(trip_path, cam_name, slice_name+".png"))
            if cam_name in outlier_cam_list:
                outlier_cam_img_idx.append(idx)
            idx += 1
    img_num = idx

    return img_num, outlier_cam_img_idx


def parse_trip_calib(trip_path, read_colmap_res=False):
    """
    Given a trip, return the paths of all images and image-wise poses
    """
    raw_trip_calib = json.load(open(os.path.join(trip_path, "calib.json"), "r"))
    seg_mask_path = trip_path.replace("/image/", "/seg_mask/")
    outlier_cam_list = raw_trip_calib.get("outlier_cam_list", [])
    cam_list = [x for x in os.listdir(seg_mask_path) if "cam" in x and x not in outlier_cam_list]
    cam_list.sort()

    trip_calib = {}
    img_paths, global_poses,local_poses = [], [], []
    intrinsics, extrinsics = [], []
    for cam_name in cam_list:
        num_slice = 0
        contents_cam_dir = os.listdir(os.path.join(seg_mask_path, cam_name))
        for item in contents_cam_dir:
            if 'slice' in item:
                num_slice += 1

        for slice_idx in range(num_slice):
            slice_name = f"slice{slice_idx}"
            img_paths.append(os.path.join(trip_path, cam_name, slice_name+".png"))
            global_poses.append(np.array(raw_trip_calib["global_pose"][slice_name]))
            local_poses.append(np.array(raw_trip_calib["local_pose"][slice_name]))

            intrinsic = np.zeros((3, 3))
            intrinsic[0, 0] = raw_trip_calib[cam_name]["intrinsic"]["focal_length"]
            intrinsic[1, 1] = raw_trip_calib[cam_name]["intrinsic"]["focal_length"]
            intrinsic[0, 2] = raw_trip_calib[cam_name]["intrinsic"]["cx"]
            intrinsic[1, 2] = raw_trip_calib[cam_name]["intrinsic"]["cy"]
            intrinsic[2, 2] = 1
            intrinsics.append(intrinsic)

            extrinsic = np.array(raw_trip_calib[cam_name]["extrinsic"]["transformation_matrix"])
            extrinsics.append(extrinsic)

    trip_calib = {"img_paths": img_paths,
                  "local_poses": np.array(local_poses),
                  "global_poses": np.array(global_poses),
                  "intrinsics": np.array(intrinsics),
                  "extrinsics": np.array(extrinsics),
                  "cam_image_size": raw_trip_calib.get("cam_image_size", {}),
                  "cam_list": cam_list,
                  }

    if read_colmap_res:
        colmap_intrinsics, colmap_extrinsics = [], []
        for cam_name in os.listdir(trip_path):
            if "cam" not in cam_name:
                continue
            num_slice = len(os.listdir(os.path.join(trip_path, cam_name)))
            for slice_idx in range(num_slice):
                slice_name = f"slice{slice_idx}"

                intrinsic = np.zeros((3, 3))
                intrinsic[0, 0] = raw_trip_calib['colmap_intrinsic'][cam_name]["focal_length"]
                intrinsic[1, 1] = raw_trip_calib['colmap_intrinsic'][cam_name]["focal_length"]
                intrinsic[0, 2] = raw_trip_calib['colmap_intrinsic'][cam_name]["cx"]
                intrinsic[1, 2] = raw_trip_calib['colmap_intrinsic'][cam_name]["cy"]
                intrinsic[2, 2] = 1

                colmap_intrinsics.append(np.array(intrinsic))
                colmap_extrinsics.append(np.array(raw_trip_calib["colmap_extrinsic"][f"{slice_name}_{cam_name}"]))
        trip_calib.update({"colmap_intrinsics": np.array(colmap_intrinsics), \
                           "colmap_extrinsics": np.array(colmap_extrinsics)})

    return trip_calib


def convert_rel_to_abs_dict(trip_info, save_dir):
    """ Convert keys in trip_info from absolute path to relative path """
    for trip_path in trip_info.copy().keys():
        if not os.path.isabs(trip_path):
            trip_info[os.path.join(save_dir, trip_path)] = trip_info.pop(trip_path)
    return trip_info


def concat_cam_imgs(slice, img_h=400, img_w=800):
    """
    Concatenate all camera images in a slice.
    """
    img_h, img_w = 400, 800
    dummy_im = np.zeros((img_h, img_w, 3))

    im0 = slice.get("cam0", dummy_im)
    im2 = slice.get("cam2", dummy_im)
    im3 = slice.get("cam3", dummy_im)
    im4 = slice.get("cam4", dummy_im)
    im5 = slice.get("cam5", dummy_im)
    im6 = slice.get("cam6", dummy_im)
    im7 = slice.get("cam7", dummy_im)

    im0 = cv2.resize(im0, (img_w, img_h))
    im2 = cv2.resize(im2, (img_w, img_h))
    im3 = cv2.resize(im3, (img_w, img_h))
    im4 = cv2.resize(im4, (img_w, img_h))
    im5 = cv2.resize(im5, (img_w, img_h))
    im6 = cv2.resize(im6, (img_w, img_h))
    im7 = cv2.resize(im7, (img_w, img_h))

    cat_im = np.zeros((img_h*5, img_w*2, 3), dtype=np.uint8)
    cat_im[0*img_h:1*img_h, img_w//2:img_w//2+img_w] = im0
    cat_im[1*img_h:2*img_h, img_w//2:img_w//2+img_w] = im2
    cat_im[2*img_h:3*img_h, 0*img_w:1*img_w] = im3
    cat_im[2*img_h:3*img_h, 1*img_w:2*img_w] = im4
    cat_im[3*img_h:4*img_h, 0*img_w:1*img_w] = im5
    cat_im[3*img_h:4*img_h, 1*img_w:2*img_w] = im6
    cat_im[4*img_h:5*img_h, img_w//2:img_w//2+img_w] = im7

    return cat_im

def kill_all_cuda_python_process():
    os.system(r"nvidia-smi | grep 'python' | awk '{ print $5 }' | xargs -n1 kill -9")

def merge_local_pose_odom(exp_dir, all_trips):
    image_name_local_pose_odom_dict = dict()
    for full_trip_name in all_trips:
        trip_name = "/".join(full_trip_name.split("/")[-2:])
        local_pose_file = os.path.join(exp_dir, "sparse", trip_name, "odom_pose.txt")
        colmap_model_dir = os.path.join(exp_dir, "bundled", trip_name)
        if os.path.exists(os.path.join(colmap_model_dir, "images.bin")):
            images = read_write_model.read_images_binary(os.path.join(colmap_model_dir, "images.bin"))
        elif os.path.exists(os.path.join(colmap_model_dir, "images.txt")):
            images = read_write_model.read_images_text(os.path.join(colmap_model_dir, "images.txt"))
        else:
            raise Exception("No colmap model found.")

        image_id_name_dict = dict()
        for image_id, image in images.items():
            image_id_name_dict[image_id] = image.name

        with open(local_pose_file, "r") as fd:
            for line in fd.readlines():
                splits = line.replace("\n", "").split(",")
                image0, image1 = image_id_name_dict[int(splits[0])], image_id_name_dict[int(splits[1])]
                image_name_local_pose_odom_dict[(image0, image1)] = splits[2:]

    db = colmap_db.COLMAPDatabase.connect(os.path.join(exp_dir, "merge/database.db"))
    image_name_id_dict = dict()
    for image_id, image_name in db.execute("SELECT image_id, name FROM images"):
        image_name_id_dict[image_name] = image_id
    db.close()

    with open(os.path.join(exp_dir, "merge/odom_pose.txt"), "w+") as merged_odom_pose_fd:
        for image_pair, odom_pose in image_name_local_pose_odom_dict.items():
            image_id0, image_id1 = image_name_id_dict[image_pair[0]], image_name_id_dict[image_pair[1]]
            merged_odom_pose_fd.write(f"{image_id0},{image_id1}")
            for i in odom_pose:
                merged_odom_pose_fd.write(f",{i}")
            merged_odom_pose_fd.write("\n")


def merge_local_pose_odom_reloc(merge_map_dir, cur_trip):
    image_name_local_pose_odom_dict = dict()
    sparse_model_dir = cur_trip.replace("image", "sparse")
    odom_pose_file = os.path.join(sparse_model_dir, "odom_pose.txt")
    colmap_images_file = os.path.join(sparse_model_dir, "images.txt")
    if os.path.exists(colmap_images_file):
        colmap_images = read_write_model.read_images_text(colmap_images_file)
    else:
        colmap_images_file = os.path.join(sparse_model_dir, "images.bin")
        colmap_images = read_write_model.read_images_binary(colmap_images_file)

    image_id_name_dict = dict()
    for image_id, image in colmap_images.items():
        image_id_name_dict[image_id] = image.name
    with open(odom_pose_file, "r") as fd:
        for line in fd.readlines():
            splits = line.replace("\n", "").split(",")
            image0, image1 = image_id_name_dict[int(splits[0])], image_id_name_dict[int(splits[1])]
            image_name_local_pose_odom_dict[(image0, image1)] = splits[2:]

    # TODO(@zhangx40): merge odom_pose in recon map merge. Since recon map is fixed in reloc mode, it's safe to not merge it currently.

    db = colmap_db.COLMAPDatabase.connect(os.path.join(sparse_model_dir, "database.db"))
    image_name_id_dict = dict()
    for image_id, image_name in db.execute("SELECT image_id, name FROM images"):
        image_name_id_dict[image_name] = image_id
    db.close()

    merged_odom_pose_fd = open(os.path.join(merge_map_dir, "odom_pose.txt"), "w+")
    for image_pair, odom_pose in image_name_local_pose_odom_dict.items():
        image_id0, image_id1 = image_name_id_dict[image_pair[0]], image_name_id_dict[image_pair[1]]
        merged_odom_pose_fd.write(f"{image_id0},{image_id1}")
        for i in odom_pose:
            merged_odom_pose_fd.write(f",{i}")
        merged_odom_pose_fd.write("\n")
    merged_odom_pose_fd.close()

def dump_optimized_cam_extrinsics(opt_extrinsics, cam_name_id_dict, output_dir):
    print(f"=======optimized cam2rig extrinsic changes(meter\degree):========")
    opt_ext_json = dict()
    for idx, cam_name in enumerate(cam_name_id_dict.keys()):
        cam2rig = np.linalg.inv(opt_extrinsics[idx])
        euler = np.round(ScipyRot.from_matrix(cam2rig[:3, :3]).as_euler("XYZ", degrees=True), 2)
        trans = np.round(cam2rig[:3, 3], 3)
        print(f"  {cam_name}: trans: {trans}, rot(\u00b0): {euler}")
        if cam_name not in opt_ext_json:
            opt_ext_json[cam_name] = dict()
        opt_ext_json[cam_name]["cam_to_rig_matrix"] = cam2rig.tolist()
        opt_ext_json[cam_name]["cam_to_rig_translation"] = trans.tolist()
        opt_ext_json[cam_name]["cam_to_rig_rotation_euler"] = euler.tolist()
    os.makedirs(output_dir, exist_ok=True)
    with open(os.path.join(output_dir, "rome_optimized_extrinsics.json"), "w+") as fd:
        json.dump(opt_ext_json, fd, indent=2)
    print("==================================================================")


def print_trip_json_stats(logger, trip_json_path):
    logger.info(f"Trip json path: {trip_json_path}")
    trip_dict = json.load(open(trip_json_path, 'r'))
    logger.info(f"Number of trips: {len(trip_dict)}")
    num_clips = 0
    for trip_path, clip_list in trip_dict.items():
        num_clips += len(clip_list)
    logger.info(f"Number of clips: {num_clips}")



def move_mvsnet_depth(config):
    """
    Move the mvsnet depth images to the original folder of mvs depth.
    """
    print("Moving MVSNet depth images ...")
    exp_dir = config["exp_dir"]
    depth_output = os.path.join(exp_dir, 'dense', 'single_depth')
    mvsnet_output_path = os.path.join(exp_dir, 'mvsnet_output')
    meta_data_path = os.path.join(exp_dir, 'mvsnet_metadata')

    for meta_data in [file for file in os.listdir(meta_data_path) if file.endswith('.json')]:
        trip = meta_data.split("_meta")[0]
        depth_output_path = os.path.join(depth_output, trip.split('_')[0], trip.split('_')[1])
        depth_path = os.path.join(mvsnet_output_path, trip, 'depth')
        depth_list = [file for file in os.listdir(depth_path) if file.endswith('.png')] # get depth img list
        with open(os.path.join(meta_data_path, meta_data), 'r') as f:
            metadata = json.load(f)
            for img_id, img_info in metadata.items():
                camid = metadata[img_id]['img_path'].split('/')[-2]
                if not os.path.exists(os.path.join(depth_output_path, img_info['cam_id'])):
                    os.makedirs(os.path.join(depth_output_path, img_info['cam_id']))
                curr_depth_output_path = os.path.join(depth_output_path, img_info['cam_id'], img_info['img_path'].split('/')[-1])
                depth = '{:0>8}.png'.format(img_id)
                depth_input_path = os.path.join(depth_path, depth)
                # If the symlink already exists, remove it
                if os.path.islink(curr_depth_output_path):
                    os.unlink(curr_depth_output_path)
                os.symlink(depth_input_path, curr_depth_output_path)


if __name__=="__main__":
    generate_trip_cam_videos()
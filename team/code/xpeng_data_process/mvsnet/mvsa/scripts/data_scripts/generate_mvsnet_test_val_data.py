import numpy as np
import os
import json

def slice_id(path):
    return int(path.split('/')[-1].split('.')[0][5:])

def generate_mvsnet_metadata(trip_path, mode):
    clip_path = trip_path # root path
    for suffix in ['image', 'recon', 'vision']:
        if clip_path.endswith(os.sep + suffix):
            clip_path = os.path.dirname(clip_path)
    transform_path = os.path.join(clip_path, 'transform.json')
    with open(transform_path, 'r') as f:
        transform_info = json.load(f)
    anchor_path = os.path.join(clip_path, 'anchorpose.json')
    with open(anchor_path, 'r') as f:
        anchor_pose = json.load(f)
        anchor_pose = np.array(anchor_pose)
    calib_path = os.path.join(clip_path, 'calib.json')
    with open(calib_path, 'r') as f:
        calib = json.load(f)

    image_timestamps_path = os.path.join(trip_path, 'image_timestamps.json')
    with open(image_timestamps_path, 'r') as f:
        image_timestamps = json.load(f)
    slice2timestamp = {}
    first_cam = list(image_timestamps.keys())[0]
    for slice_name, timestamp in image_timestamps[first_cam].items():
        if slice_name.startswith('slice'):
            slice_idx = int(slice_name[5:])
            slice2timestamp[slice_idx] = str(timestamp)

    rgb_path = trip_path
    trip_metadata = {}
    cam_list = os.listdir(rgb_path)
    cam_list = [name for name in cam_list if 'cam' in name]
    cam_list.sort()
    count = 0

    frames_dict = {}
    for frame in transform_info['frames']:
        timestamp = frame['timestamp']
        camera_id = frame['camera']
        key = f"{camera_id}_{timestamp}"
        frames_dict[key] = {
            "file_path": frame['file_path'],
            "transform_matrix": frame['transform_matrix']
        }

    for cam_id in cam_list:
        images = os.listdir(os.path.join(rgb_path, cam_id))
        images = [name for name in images if name.endswith('.png') or name.endswith('.jpg')]
        images.sort(key=slice_id)

        last_id = None
        next_id = None
        for img_name in images:
            slice_name = img_name.split('.')[0]
            if slice_name.startswith('slice'):
                slice_idx = int(slice_name[5:])
            else:
                print(f"Warning: Unexpected image name format: {img_name}")
                continue
            if slice_idx not in slice2timestamp:
                print(f"Warning: slice_id {slice_idx} not found in timestamp2slice.json")
                continue
            cur_timestamp = slice2timestamp[slice_idx]
            cur_frame_dict = frames_dict[f"{cam_id}_{cur_timestamp}"]
            pose = np.array(cur_frame_dict["transform_matrix"]) # cam2anchor
            pose = pose.tolist()
            # intrinsic = transform_info['sensor_params'][cam_id]['camera_intrinsic']
            extrinsic = transform_info['sensor_params'][cam_id]['extrinsic'] # cam2rig
            
            import cv2
            actual_img_path = os.path.join(rgb_path, cam_id, img_name)
            actual_img = cv2.imread(actual_img_path)
            if actual_img is not None:
                actual_height, actual_width = actual_img.shape[:2]
                img_size = [actual_width, actual_height]  # [w, h]
            else:
                img_size = [transform_info['sensor_params'][cam_id]['width'], transform_info['sensor_params'][cam_id]['height']] # [w, h]
            
            intri = calib[cam_id]['intrinsic'] # 3x3 matrix
            intrinsic = np.eye(3)
            intrinsic[0, 0] = intri['focal_length']
            intrinsic[1, 1] = intri['focal_length']
            intrinsic[0, 2] = intri['cx']
            intrinsic[1, 2] = intri['cy']
            intrinsic = intrinsic.tolist()

            trip_metadata[count] = {}
            trip_metadata[count]['pose'] = pose
            trip_metadata[count]['intrinsic'] = intrinsic
            trip_metadata[count]['img_path'] = os.path.join(rgb_path, cam_id, img_name)
            # trip_metadata[count]['depth_path'] = os.path.join(rgb_path.replace('images', 'depth_new'), cam_id, img_name.replace('.png', '.npy'))
            trip_metadata[count]['seg_path'] = os.path.join(rgb_path.replace('image', 'seg_mask'), cam_id, img_name)
            # trip_metadata[count]['mask_path'] = os.path.join(rgb_path.replace('images', 'masks'), cam_id, img_name)
            trip_metadata[count]['cam_id'] = cam_id
            trip_metadata[count]['id'] = count
            trip_metadata[count]['last_id'] = last_id
            trip_metadata[count]['extrinsic'] = extrinsic
            trip_metadata[count]['cam_image_size'] = img_size
            trip_metadata[count]['next_id'] = count + 1
            last_id = count
            count += 1

    # update next_id for all frame
    for id in trip_metadata:
        next_idx = trip_metadata[id]['next_id']
        if next_idx not in trip_metadata.keys():
            trip_metadata[id]['next_id'] = None
        else:
            tmp_id = trip_metadata[next_idx]['last_id']
            if tmp_id != id:
                trip_metadata[id]['next_id'] = None
                
    # get src image for each ref image
    MAX_RANGE = 5
    TARGET_SRC_COUNT = MAX_RANGE * 2
    for id in trip_metadata:
        assert id == trip_metadata[id]['id']
        ref_cam_id = trip_metadata[id]['cam_id']
        # get the src image from last and next
        last_id = trip_metadata[id]['last_id']
        left = []
        while last_id is not None and len(left) < MAX_RANGE:
            if trip_metadata[last_id]['cam_id'] == ref_cam_id:
                left.append(last_id)
                last_id = trip_metadata[last_id]['last_id']
            else:
                break
        
        next_id = trip_metadata[id]['next_id']
        right = []
        while next_id is not None and len(right) < MAX_RANGE:
            if trip_metadata[next_id]['cam_id'] == ref_cam_id:
                right.append(next_id)
                next_id = trip_metadata[next_id]['next_id']
            else:
                break
        
        if len(left) + len(right) >= MAX_RANGE:
            src_views = []
            for i in range(max(len(left), len(right))):
                if i < len(left):
                    src_views.append(left[i])
                if i < len(right):
                    src_views.append(right[i])

            if src_views:
                seen = set()
                src_views_filtered = []
                for src_id in src_views:
                    # Check if valid and not duplicate
                    if (src_id in trip_metadata and
                        trip_metadata[src_id]['cam_id'] == ref_cam_id and
                        src_id not in seen):
                        seen.add(src_id)
                        src_views_filtered.append(src_id)
                src_views = src_views_filtered
                
                if src_views:
                    if len(src_views) > TARGET_SRC_COUNT:
                        src_views = src_views[:TARGET_SRC_COUNT]

            trip_metadata[id]['src_views'] = src_views
    
    return trip_metadata


def convert_to_capture_format(trip_metadata, output_path):
    sorted_ids = sorted(trip_metadata.keys())

    capture_data = {
        "frames": {},
        "formatVersion": "1",
        "frameCount": len(sorted_ids),
        "resolution": [1920, 1080],
        "imageFormat": "png",
        "manufacturer": "Xpeng",
        "depthSource": "lidar"
    }
    
    for frame_id in sorted_ids:
        frame_data = trip_metadata[frame_id]
        
        frame_entry = {
            "resolution": frame_data['cam_image_size'],  # [w, h]
            "depthResolution": frame_data['cam_image_size'],  # [w, h]
            "image": frame_data['img_path'],
            # 'depth': frame_data['depth_path'],
            "seg": frame_data['seg_path'],
            # "mask": frame_data['mask_path'],
            "intrinsics": frame_data['intrinsic'],
            "pose4x4": frame_data['pose'],
            "sequence": frame_id,
            "camera_id": frame_data['cam_id']
        }
        
        if 'src_views' in frame_data:
            src_views_with_info = []
            seen_src_ids = set()
            for src_id in frame_data['src_views']:
                if src_id in trip_metadata and src_id not in seen_src_ids:
                    seen_src_ids.add(src_id)
                    src_frame_data = trip_metadata[src_id]
                    src_views_with_info.append({
                        'id': src_id,
                        'frame_id': src_id,
                        'cam_id': src_frame_data['cam_id']
                    })
            frame_entry['src_views'] = src_views_with_info
            
            if len(src_views_with_info) < len(frame_data['src_views']):
                print(f"Warning: Removed {len(frame_data['src_views']) - len(src_views_with_info)} duplicate source views for frame {frame_id} in capture.json")
        
        capture_data["frames"][str(frame_id)] = frame_entry
    
    with open(output_path, 'w') as f:
        json.dump(capture_data, f, indent=2)
    
    print(f"Capture.json saved to: {output_path}")


def output_view_list(trip_metadata, output_path):
    sorted_ids = sorted(trip_metadata.keys())
    
    duplicate_count = 0
    with open(output_path, 'w') as f:
        for id in sorted_ids:
            line_parts = ['xpeng', str(id)]
            
            if 'src_views' in trip_metadata[id]:
                src_views = trip_metadata[id]['src_views']
                seen = set()
                src_views_unique = []
                for src_id in src_views:
                    if src_id not in seen:
                        seen.add(src_id)
                        src_views_unique.append(src_id)
                    else:
                        duplicate_count += 1
                
                for src_id in src_views_unique:
                    line_parts.append(str(src_id))
                
                if len(src_views_unique) < len(src_views):
                    print(f"Warning: Removed {len(src_views) - len(src_views_unique)} duplicate source views for frame {id} in tuple file")
            
            f.write(' '.join(line_parts) + '\n')
    
    if duplicate_count > 0:
        print(f"Warning: Total {duplicate_count} duplicate source views removed across all tuples")
    print(f"Output saved to: {output_path}")


def generate_metadata(trip_path, mode):
    trip_metadata = generate_mvsnet_metadata(trip_path, mode)
    with open(os.path.join(trip_path, 'metadata.json'), 'w') as f:
        json.dump(trip_metadata, f, indent=4)
    
    txt_output_path = os.path.join(trip_path, 'test_xpeng_tuple.txt')
    output_view_list(trip_metadata, txt_output_path)
    
    capture_output_path = os.path.join(trip_path, 'capture.json')
    convert_to_capture_format(trip_metadata, capture_output_path)
    
    return trip_metadata


if __name__ == '__main__':
    # parser = argparse.ArgumentParser()
    # parser.add_argument("--trip_path", type=str, required=True, help="Path to exp_dir")
    # parser.add_argument("--mode", type=str, required=True, help="test or val")
    # args = parser.parse_args()
    # assert args.mode in ['test', 'val']
    # generate_metadata(args.mode, args.trip_path)

    trip_path = "/workspace/group_share/adc-sim/users/zf/vision_exp/lidar/c-43df1bb8-eb78-37af-b4fa-1e0c71f339ad"
    mode = "test"
    generate_metadata(mode, trip_path)
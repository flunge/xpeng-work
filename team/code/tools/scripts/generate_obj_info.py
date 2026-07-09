import os
import json
import numpy as np
import matplotlib.pyplot as plt
import yaml


def read_quat_and_trans(dir_name, gid):
    anno_file = os.path.join(dir_name, "configs/config_sim.yaml")
    data = yaml.load(open(anno_file), Loader=yaml.CSafeLoader)
    data = data['results']['annotations']

    filtered_data = []
    for frame in data.get('frames', []):
        timestamp = frame.get('timestamp')
        for obj in frame.get('objects', []):
            if obj.get('gid') == gid:
                extracted_entry = {
                    'timestamp': timestamp,
                    'translation': obj.get('translation'),
                    'rotation': obj.get('rotation')
                }
                filtered_data.append(extracted_entry)
    
    filtered_data.sort(key=lambda x: x['timestamp'])

    timestamp = []
    original_quats = []
    original_trans = []
    for pose in filtered_data:
        timestamp.append(pose["timestamp"])
        original_quats.append(pose["rotation"])
        original_trans.append(pose["translation"])

    gid_to_localid = {}
    localid = 0
    for frame in data["frames"]:
        for o in frame["objects"]:
            if o["gid"] not in gid_to_localid:
                gid_to_localid[o["gid"]] = localid
                localid += 1
    return original_quats, original_trans, timestamp, gid_to_localid[gid]

def quat_to_euler(q):
    w, x, y, z = q
    sinr_cosp = 2 * (w * x + y * z)
    cosr_cosp = 1 - 2 * (x * x + y * y)
    roll = np.arctan2(sinr_cosp, cosr_cosp)
    sinp = 2 * (w * y - z * x)
    if np.abs(sinp) >= 1:
        pitch = np.sign(sinp) * np.pi / 2
    else:
        pitch = np.arcsin(sinp)
    siny_cosp = 2 * (w * z + x * y)
    cosy_cosp = 1 - 2 * (y * y + z * z)
    yaw = np.arctan2(siny_cosp, cosy_cosp)
    return roll, pitch, yaw

def euler_to_quat(roll, pitch, yaw):
    cr, sr = np.cos(roll*0.5), np.sin(roll*0.5)
    cp, sp = np.cos(pitch*0.5), np.sin(pitch*0.5)
    cy, sy = np.cos(yaw*0.5), np.sin(yaw*0.5)
    w = cr*cp*cy + sr*sp*sy
    x = sr*cp*cy - cr*sp*sy
    y = cr*sp*cy + sr*cp*sy
    z = cr*cp*sy - sr*sp*cy
    return np.array([w, x, y, z])

def generate_left_turn_trajectory(
    original_quats,
    original_trans,
    T_start,
    turn_radius=20.0,    # 转弯半径（米），越小越急
    max_turn_angle=np.pi / 2,  # 最大转90度（可选）
    dt=1.0              # 帧时间间隔（秒），若无时间信息可设为1
):
    """
    Generate a realistic left-turn trajectory starting at T_start.
    - Before T_start: unchanged.
    - At/After T_start: constant-radius left turn (circular arc).
    - Preserves original roll/pitch; only updates yaw.
    """
    original_quats = np.array(original_quats)
    original_trans = np.array(original_trans)
    N = len(original_trans)

    new_trans = original_trans.copy()
    new_quats = original_quats.copy()

    # No modification if T_start >= N
    if T_start >= N:
        print("T_start ", T_start)
        print("N ", N)
        return new_quats, new_trans

    # === Step 1: Extract initial state at T_start ===
    x0, y0, z0 = original_trans[T_start]
    yaw0 = np.arctan2(
        2 * (original_quats[T_start][0] * original_quats[T_start][3] + 
             original_quats[T_start][1] * original_quats[T_start][2]),
        1 - 2 * (original_quats[T_start][2]**2 + original_quats[T_start][3]**2)
    )

    count_id = 0
    avg_speed = 0
    for curr_id in range(T_start, min(T_start + 40, N)):
        dx = original_trans[curr_id, 0] - original_trans[curr_id-1, 0]
        dy = original_trans[curr_id, 1] - original_trans[curr_id-1, 1]
        speed = np.sqrt(dx**2 + dy**2) / dt  # m/frame
        avg_speed += speed
        count_id += 1
    if count_id > 0:
        avg_speed /= count_id
    else:
        avg_speed = 1e-3
    print("Avg Speed: ", avg_speed)

    # Avoid division by zero
    speed = max(avg_speed, 1e-3)

    # === Step 2: Generate left-turn arc (constant radius) ===
    omega = speed / turn_radius  # angular velocity (rad/frame)

    for i in range(T_start, N):
        t = (i - T_start) * dt
        delta_yaw = omega * t

        # Optional: limit total turn angle
        if delta_yaw > max_turn_angle:
            delta_yaw = max_turn_angle
            omega = 0  # stop turning after max angle

        new_yaw = yaw0 + delta_yaw

        # Circular arc position (left turn: +yaw => +Y curvature)
        if abs(omega) < 1e-6:
            # Go straight if omega ~ 0
            x = x0 + speed * t * np.cos(yaw0)
            y = y0 + speed * t * np.sin(yaw0)
        else:
            R = speed / omega
            x = x0 + R * (np.sin(new_yaw) - np.sin(yaw0))
            y = y0 - R * (np.cos(new_yaw) - np.cos(yaw0))

        # Update position (keep z unchanged)
        new_trans[i] = [x, y, z0]

        # Update orientation: keep original roll/pitch, use new_yaw
        orig_roll, orig_pitch, _ = quat_to_euler(original_quats[T_start])  # or [i]?
        new_quats[i] = euler_to_quat(orig_roll, orig_pitch, new_yaw)

    print("Finish Generate")
    return new_quats, new_trans

def quat_to_yaw(q):
    """Convert quaternion [w, x, y, z] to yaw angle in radians."""
    w, x, y, z = q
    siny_cosp = 2 * (w * z + x * y)
    cosy_cosp = 1 - 2 * (y * y + z * z)
    return np.arctan2(siny_cosp, cosy_cosp)

def display_two_trajectories(origin_quats, origin_trans, new_quats, new_trans):
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(12, 5))
    
    # Auto compute shared axis limits for fair comparison
    all_x = np.concatenate([np.array(origin_trans)[:, 0], np.array(new_trans)[:, 0]])
    all_y = np.concatenate([np.array(origin_trans)[:, 1], np.array(new_trans)[:, 1]])
    x_min, x_max = all_x.min() - 1, all_x.max() + 1
    y_min, y_max = all_y.min() - 1, all_y.max() + 1

    def plot_trajectory(ax, quats, trans, title, rect_color, point_color):
        ax.set_aspect('equal')
        ax.set_xlim(x_min, x_max)
        ax.set_ylim(y_min, y_max)
        for i in range(len(trans)):
            x, y = trans[i][0], trans[i][1]
            yaw_deg = np.degrees(quat_to_yaw(quats[i]))
            rect = plt.Rectangle(
                (x - 1, y - 0.5), 
                2, 1, 
                angle=yaw_deg, 
                fill=None, 
                edgecolor=rect_color,
                linewidth=1.2
            )
            ax.add_patch(rect)
            ax.plot(x, y, color=point_color, marker='o', markersize=3)
        ax.set_xlabel('Translation X')
        ax.set_ylabel('Translation Y')
        ax.set_title(title)
        ax.grid(True)

    # Plot original and new trajectories
    plot_trajectory(ax1, origin_quats, origin_trans, 'Original Trajectory', 'r', 'b')
    plot_trajectory(ax2, new_quats, new_trans, 'Modified Trajectory', 'g', 'orange')

    plt.tight_layout()
    plt.savefig('trajectory_comparison.png')

def save_obj_json(new_quats, new_trans, timestamps, gid, local_id, json_file, all_timestamps):
    frames = []
    for i in range(len(timestamps)):
        objects = []
        obj = {
            "gid": gid,
            "local_id": local_id,
            "translation": new_trans[i].tolist(),
            "rotation": new_quats[i].tolist()
        }
        objects.append(obj)

        index = find_time_index(timestamps[i], all_timestamps)
        frame = {
            "index": index,
            "timestamp": timestamps[i],
            "objects": objects
        }
        frames.append(frame)

    new_data = {"modified_frames": frames}
    with open(json_file, 'w') as f:
        json.dump(new_data, f, indent=4)
    print(f"New JSON saved to {json_file}")
    return

def modify_obj_trajectory(dir_name, modify_gid, output_json_file, all_timestamps):
    if modify_gid is None:
        new_data = {"modified_frames": []}
        with open(output_json_file, 'w') as f:
            json.dump(new_data, f, indent=4)
        print(f"Empty modified_frames saved to {output_json_file} (modify_gid is None)")
        return

    original_quats, original_trans, timestamp, local_id = read_quat_and_trans(dir_name, modify_gid)
    print("Local ID: ", local_id)
    np.savetxt("ori_quats.txt", original_quats, fmt='%.6f')
    np.savetxt("ori_trans.txt", original_trans, fmt='%.6f')

    turn_radius = 60.0
    new_quats, new_trans = generate_left_turn_trajectory(
        original_quats, original_trans, T_start=200, turn_radius=turn_radius
    )
    display_two_trajectories(original_quats, original_trans, new_quats, new_trans)
    print("Original Quats Len: ", len(original_quats))
    print("Original Trans Len: ", len(original_trans))
    print("New Quats Len: ", len(new_quats))
    print("New Trans Len: ", len(new_trans))
    np.savetxt("new_quats.txt", new_quats, fmt='%.6f')
    np.savetxt("new_trans.txt", new_trans, fmt='%.6f')

    save_obj_json(new_quats, new_trans, timestamp, modify_gid, local_id, output_json_file, all_timestamps)

def find_time_index(query_time, all_timestamps):
    for idx, curr_time in enumerate(all_timestamps):
        if int(curr_time) == int(query_time):
            return idx
    print("Error! Do not find match time: ", query_time)
    return None

def add_mask_obj_frames(dir_name, mask_gids, start_mask_frame_id, output_json_file, all_timestamps):
    if mask_gids is None or len(mask_gids) == 0:
        if os.path.exists(output_json_file):
            with open(output_json_file, 'r') as f:
                data = json.load(f)
            data['mask_obj_frames'] = []
            with open(output_json_file, 'w') as f:
                json.dump(data, f, indent=4)
            print(f"Empty mask_obj_frames added to existing {output_json_file} (mask_gids is empty)")
        else:
            new_data = {"mask_obj_frames": []}
            with open(output_json_file, 'w') as f:
                json.dump(new_data, f, indent=4)
            print(f"Empty mask_obj_frames saved to {output_json_file} (mask_gids is empty, no existing file)")
        return

    mask_frames_data = []
    for mask_gid in mask_gids:
        original_quats, original_trans, timestamp_list, local_id = read_quat_and_trans(dir_name, mask_gid)

        for index, timestamp in enumerate(timestamp_list):
            vis = True
            if index >= start_mask_frame_id:
                vis = False

            index = find_time_index(timestamp, all_timestamps)
            mask_frames_data.append({
                "index": index,
                "timestamp": timestamp,
                "local_id": local_id,
                "gid": mask_gid,
                "vis": vis
            })

    if os.path.exists(output_json_file):
        with open(output_json_file, 'r') as f:
            modified_data = json.load(f)
    else:
        modified_data = {}

    modified_data['mask_obj_frames'] = mask_frames_data
    with open(output_json_file, 'w') as f:
        json.dump(modified_data, f, indent=4)


def get_all_timestamps(dir_name):
    json_file_path = os.path.join(dir_name, "localpose.json")
    with open(json_file_path, 'r') as f:
        data = json.load(f)
    
    timestamps = []
    for key in data.keys():
        timestamps.append(int(key))
    timestamps.sort()
    return timestamps


def main():
    clip_id = "c-d79e4adf-7878-3b6c-b711-53d3914377f8"
    dir_name = f"/workspace/yangxh7@xiaopeng.com/cloudsim_model/{clip_id}/trained_model_sim3dgs_v411b_1347/"
    modify_gid = None
    all_timestamps = get_all_timestamps(dir_name)

    output_json_file = os.path.join(dir_name, "modified_obj.json")
    modify_obj_trajectory(dir_name, modify_gid, output_json_file, all_timestamps)

    mask_gids = [80622, 82166]
    start_mask_frame_id = 0 
    add_mask_obj_frames(dir_name, mask_gids, start_mask_frame_id, output_json_file, all_timestamps)


if __name__ == "__main__":
    main()
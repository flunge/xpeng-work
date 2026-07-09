import os
import re
import csv
import numpy as np

# ROOT_DIR = "/workspace/group_share/adc-sim/users/yangxh7/logs/sim3dgs_v406/"
MODEL_VERSION = "sim3dgs_v406"
ROOT_DIR = f"/workspace/group_share/adc-sim/users/yangxh7/logs/{MODEL_VERSION}/"
LOG_FILENAME = "log.txt"
OUTPUT_CSV = f"gaussian_stats_{MODEL_VERSION}.csv"

# 正则
re_init = re.compile(r"Initialized (\w+) gaussians with (\d+) points")
re_step = re.compile(r"\[\s*(\d+)/")
re_g_bg = re.compile(r"gaussian_num_Background:\s*([\d\.]+)")
re_g_rigid = re.compile(r"gaussian_num_RigidNodes:\s*([\d\.]+)")
re_g_ground = re.compile(r"gaussian_num_Ground:\s*([\d\.]+)")


def parse_log(log_path):
    """解析单个 log.txt，返回点数统计结果。"""
    init_bg = init_rigid = init_ground = None
    last_bg = last_rigid = last_ground = None
    last_step = -1

    if not os.path.exists(log_path):
        return None

    with open(log_path, "r") as f:
        for line in f:
            # 初始化
            m = re_init.search(line)
            if m:
                name, pts = m.group(1), int(m.group(2))
                if name == "Background":
                    init_bg = pts
                elif name == "RigidNodes":
                    init_rigid = pts
                elif name == "Ground":
                    init_ground = pts

            # 训练中
            if "gaussian_num_Background" in line:
                step_m = re_step.search(line)
                if not step_m:
                    continue
                step = int(step_m.group(1))

                m_bg = re_g_bg.search(line)
                m_rigid = re_g_rigid.search(line)
                m_ground = re_g_ground.search(line)

                if m_bg and m_rigid and m_ground and step > last_step:
                    last_step = step
                    last_bg = float(m_bg.group(1))
                    last_rigid = float(m_rigid.group(1))
                    last_ground = float(m_ground.group(1))

    return {
        "init_bg": init_bg,
        "init_rigid": init_rigid,
        "init_ground": init_ground,
        "final_step": last_step,
        "final_bg": last_bg,
        "final_rigid": last_rigid,
        "final_ground": last_ground,
    }


# --- 遍历所有 clip ---
clip_dirs = [
    d for d in os.listdir(ROOT_DIR)
    if os.path.isdir(os.path.join(ROOT_DIR, d)) and d.startswith("c-")
]
clip_dirs.sort()

print(f"Found {len(clip_dirs)} clip folders.")

results = []

for clip in clip_dirs:
    log_path = os.path.join(ROOT_DIR, clip, LOG_FILENAME)
    res = parse_log(log_path)
    if res is None:
        print(f"WARNING: No log.txt found in {clip}")
        continue
    results.append([clip] + list(res.values()))


# --- 写 CSV ---
header = [
    "clip_id",
    "init_bg", "init_rigid", "init_ground",
    "final_step", "final_bg", "final_rigid", "final_ground"
]

with open(OUTPUT_CSV, "w", newline="") as f:
    writer = csv.writer(f)
    writer.writerow(header)
    writer.writerows(results)

print(f"\nCSV written to: {OUTPUT_CSV}\n")


# --- 计算平均值 ---
# 转成 numpy 方便统计
init_bg_list = np.array([r[1] for r in results], dtype=float)
init_rigid_list = np.array([r[2] for r in results], dtype=float)
init_ground_list = np.array([r[3] for r in results], dtype=float)

final_bg_list = np.array([r[5] for r in results], dtype=float)
final_rigid_list = np.array([r[6] for r in results], dtype=float)
final_ground_list = np.array([r[7] for r in results], dtype=float)

# 变化量
delta_bg = final_bg_list - init_bg_list
delta_rigid = final_rigid_list - init_rigid_list
delta_ground = final_ground_list - init_ground_list

# 变化比例
ratio_bg = final_bg_list / init_bg_list
ratio_rigid = final_rigid_list / init_rigid_list
ratio_ground = final_ground_list / init_ground_list


# --- 打印统计结果 ---
print("============== SUMMARY ==============")
print(f"Total clips: {len(results)}\n")

print("---- Average Initialized Points ----")
print(f"Background: {init_bg_list.mean():.2f}")
print(f"RigidNodes: {init_rigid_list.mean():.2f}")
print(f"Ground:     {init_ground_list.mean():.2f}\n")

print("---- Average Final Points ----")
print(f"Background: {final_bg_list.mean():.2f}")
print(f"RigidNodes: {final_rigid_list.mean():.2f}")
print(f"Ground:     {final_ground_list.mean():.2f}\n")

print("---- Average Δ (Final - Init) ----")
print(f"Background: {delta_bg.mean():.2f}")
print(f"RigidNodes: {delta_rigid.mean():.2f}")
print(f"Ground:     {delta_ground.mean():.2f}\n")

print("---- Average Ratio (Final / Init) ----")
print(f"Background: {ratio_bg.mean():.4f}")
print(f"RigidNodes: {ratio_rigid.mean():.4f}")
print(f"Ground:     {ratio_ground.mean():.4f}")
print("======================================\n")

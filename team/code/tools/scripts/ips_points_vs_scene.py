import os
import re
import csv
import matplotlib.pyplot as plt

MODEL_NAMES = [
    "sim3dgs_v407_baseline",
    "sim3dgs_v407_fixed_dpvo",
]
ROOT_DIR_TEMPLATE = "/workspace/group_share/adc-sim/users/yangxh7/logs/{model}/"
LOG_FILENAME = "log.txt"
# OUTPUT_CSV = "gaussian_radius_stats.csv"
OUTPUT_PNG = f"points_vs_scene_{'_vs_'.join(MODEL_NAMES)}.png"  # 保存图像
CATEGORY_ORDER = [
    ("Background", "Background"),
    ("RigidNodes", "Rigid Nodes"),
    ("Ground", "Ground"),
]

# 正则表达式
re_radius = re.compile(r"scene radius:\s*([\d\.]+)")
re_init = re.compile(r"Initialized (\w+) gaussians with (\d+) points")
re_step = re.compile(r"\[\s*(\d+)/")
re_g_bg = re.compile(r"gaussian_num_Background:\s*([\d\.]+)")
re_g_rigid = re.compile(r"gaussian_num_RigidNodes:\s*([\d\.]+)")
re_g_ground = re.compile(r"gaussian_num_Ground:\s*([\d\.]+)")

def parse_log(log_path):
    scene_radius = None
    init_bg = init_rigid = init_ground = None
    last_bg = last_rigid = last_ground = None
    last_step = -1

    if not os.path.exists(log_path):
        return None

    with open(log_path, "r") as f:
        for line in f:
            # scene radius
            m_radius = re_radius.search(line)
            if m_radius:
                scene_radius = float(m_radius.group(1))

            # 初始化点数
            m_init = re_init.search(line)
            if m_init:
                name, pts = m_init.group(1), int(m_init.group(2))
                if name == "Background":
                    init_bg = pts
                elif name == "RigidNodes":
                    init_rigid = pts
                elif name == "Ground":
                    init_ground = pts

            # 训练中最后一次点数
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

    if init_bg is None or init_rigid is None or init_ground is None:
        return None

    return {
        "scene_radius": scene_radius,
        "init": {
            "Background": init_bg,
            "RigidNodes": init_rigid,
            "Ground": init_ground,
        },
        "final": {
            "Background": last_bg if last_bg is not None else 0,
            "RigidNodes": last_rigid if last_rigid is not None else 0,
            "Ground": last_ground if last_ground is not None else 0,
        },
    }


def collect_model_data(model_name):
    root_dir = ROOT_DIR_TEMPLATE.format(model=model_name)
    if not os.path.isdir(root_dir):
        print(f"WARNING: skip {model_name}, root dir not found: {root_dir}")
        return []

    clip_dirs = [
        d for d in os.listdir(root_dir)
        if os.path.isdir(os.path.join(root_dir, d)) and d.startswith("c-")
    ]
    clip_dirs.sort()

    data = []
    for clip in clip_dirs:
        log_path = os.path.join(root_dir, clip, LOG_FILENAME)
        res = parse_log(log_path)
        if res is None:
            print(f"WARNING: skip {model_name}/{clip}, missing data")
            continue
        data.append(res)
    return data

# 保存 CSV
# with open(OUTPUT_CSV, "w", newline="") as f:
#     writer = csv.DictWriter(f, fieldnames=["scene_radius","init_total","final_total"])
#     writer.writeheader()
#     writer.writerows(data)

# print(f"CSV saved: {OUTPUT_CSV}")

model_results = []
for model in MODEL_NAMES:
    data = collect_model_data(model)
    if not data:
        continue
    model_results.append((model, data))

if not model_results:
    raise SystemExit("ERROR: 没有可用的数据，检查模型名称和日志路径是否正确。")

# --- 画三个 subplot，分别展示 Background / RigidNodes / Ground ---
fig, axes = plt.subplots(len(CATEGORY_ORDER), 1, figsize=(9, 12), sharex=True)

color_cycle = plt.cm.tab10.colors
init_marker = "o"
final_marker = "s"

for ax, (category_key, category_label) in zip(axes, CATEGORY_ORDER):
    for idx, (model, data) in enumerate(model_results):
        scene_radius = [d["scene_radius"] for d in data]
        init_vals = [d["init"][category_key] for d in data]
        final_vals = [d["final"][category_key] for d in data]
        color = color_cycle[idx % len(color_cycle)]

        for x, y_init, y_final in zip(scene_radius, init_vals, final_vals):
            ax.plot([x, x], [y_init, y_final], color=color, alpha=0.5, linewidth=0.7)

        show_label = ax is axes[0]
        ax.scatter(
            scene_radius,
            init_vals,
            label=f"{model} Init" if show_label else None,
            color=color,
            marker=init_marker,
            alpha=0.8,
        )
        ax.scatter(
            scene_radius,
            final_vals,
            label=f"{model} Final" if show_label else None,
            color=color,
            marker=final_marker,
            facecolors="none",
            linewidths=1.0,
            alpha=0.8,
        )

    ax.set_ylabel(f"{category_label} Gaussians")
    ax.set_title(category_label)
    ax.grid(True, alpha=0.3)

axes[-1].set_xlabel("Scene Radius (m)")
axes[0].legend(loc="best")
fig.suptitle("Scene Radius vs Gaussians per Category")
fig.tight_layout(rect=[0, 0, 1, 0.97])
fig.savefig(OUTPUT_PNG, dpi=300)
plt.close(fig)
print(f"Multi-plot figure saved: {OUTPUT_PNG}")

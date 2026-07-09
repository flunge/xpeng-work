import json
from typing import List, Dict, Any


def check_localpose_z_anomaly(
    file_path: str,
    max_dz: float = 0.2,          # 相邻帧允许的最大高度差(米)，比如 0.5m
    max_dz_per_s: float = 2.0,    # 允许的最大竖直速度(米/秒)，比如 1 m/s
    assume_ns_timestamp: bool = True,
    verbose: bool = True
) -> List[Dict[str, Any]]:
    """
    读取 localpose.json，检查连续帧 z(高度) 是否存在不符合物理的突变。

    参数:
        file_path: localpose.json 路径
        max_dz: 相邻两帧 z 的最大绝对差值（米）
        max_dz_per_s: 相邻两帧允许的最大竖直速度（米/秒）
        assume_ns_timestamp: True 表示时间戳单位为纳秒(ns)，会自动除以 1e9 变成秒
        verbose: True 时在控制台打印异常信息

    返回:
        anomalies: 列表，每个元素是一个 dict，包含异常对的信息：
            {
                "index": 当前帧在时间序列中的索引,
                "t_prev": 上一帧时间戳(秒),
                "t_curr": 当前帧时间戳(秒),
                "z_prev": 上一帧高度,
                "z_curr": 当前帧高度,
                "dz": z_curr - z_prev,
                "dt": t_curr - t_prev,
                "dz_per_s": 竖直速度(绝对值)
            }
    """
    with open(file_path, "r") as f:
        data = json.load(f)

    # 转换为 (timestamp_int, pose_matrix) 列表，并按时间排序
    items = []
    for ts_str, mat in data.items():
        try:
            ts_int = int(ts_str)
        except ValueError:
            # 如果存在非纯数字 key，可以在这里跳过或处理
            continue
        items.append((ts_int, mat))

    items.sort(key=lambda x: x[0])

    anomalies: List[Dict[str, Any]] = []
    last_t_sec = None
    last_z = None

    for idx, (ts_int, mat) in enumerate(items):
        # 提取 z: 第3行第4列，即 mat[2][3]
        try:
            z = float(mat[2][3])
        except (IndexError, TypeError, ValueError):
            # 结构异常就跳过
            continue

        # 时间戳转为秒
        if assume_ns_timestamp:
            t_sec = ts_int / 1e9
        else:
            t_sec = float(ts_int)

        if last_t_sec is not None and last_z is not None:
            dt = t_sec - last_t_sec
            dz = z - last_z
            dz_abs = abs(dz)
            dz_per_s = dz_abs / dt if dt > 0 else float("inf")

            is_anom = False
            if dz_abs > max_dz:
                is_anom = True
            if dt > 0 and dz_per_s > max_dz_per_s:
                is_anom = True

            if is_anom:
                info = {
                    "index": idx,
                    "t_prev": last_t_sec,
                    "t_curr": t_sec,
                    "z_prev": last_z,
                    "z_curr": z,
                    "dz": dz,
                    "dt": dt,
                    "dz_per_s": dz_per_s,
                }
                anomalies.append(info)
                if verbose:
                    print(
                        f"[Z异常] idx={idx}, dz={dz:.4f} m, dt={dt:.6f} s, "
                        f"|dz|={dz_abs:.4f} m, |dz|/dt={dz_per_s:.4f} m/s"
                    )

        last_t_sec = t_sec
        last_z = z

    if verbose:
        if anomalies:
            print(f"[ERROR] 共检测到 {len(anomalies)} 处高度异常变化 {file_path}")
        else:
            print(f"[INFO] 未检测到明显的高度异常变化 {file_path}")

    return anomalies


"""Diagnostic / monitoring utilities.

All resource-status lines are prefixed with [SIMDIAG] for easy filtering in
cloud logs (e.g. `grep "[SIMDIAG]" pod.log`).
"""

import os


def log_resource_status(step_name, clip_id=""):
    """Log system resource usage at key pipeline points.

    Captures: hostname / pid / CUDA_VISIBLE_DEVICES, process RSS, system memory,
    cgroup memory limit (container/pod level), GPU allocated/reserved memory,
    GPU running processes, CPU percent.

    All lines prefixed with [SIMDIAG] for easy filtering in cloud logs.
    """
    import socket
    hostname = socket.gethostname()
    cuda_visible = os.environ.get("CUDA_VISIBLE_DEVICES", "not_set")
    pid = os.getpid()

    try:
        import psutil
        proc = psutil.Process()
        mem_info = proc.memory_info()
        rss_gb = mem_info.rss / (1024**3)
        sys_mem = psutil.virtual_memory()
        sys_avail_gb = sys_mem.available / (1024**3)
        sys_total_gb = sys_mem.total / (1024**3)
        sys_percent = sys_mem.percent
        cpu_percent = psutil.cpu_percent(interval=0.1)
    except Exception:
        rss_gb = sys_avail_gb = sys_total_gb = cpu_percent = sys_percent = -1

    # Check cgroup memory limit (container/pod level)
    cgroup_limit_gb = cgroup_usage_gb = -1
    try:
        # cgroup v2
        with open("/sys/fs/cgroup/memory.max", "r") as f:
            val = f.read().strip()
            cgroup_limit_gb = int(val) / (1024**3) if val != "max" else -1
        with open("/sys/fs/cgroup/memory.current", "r") as f:
            cgroup_usage_gb = int(f.read().strip()) / (1024**3)
    except FileNotFoundError:
        try:
            # cgroup v1
            with open("/sys/fs/cgroup/memory/memory.limit_in_bytes", "r") as f:
                val = int(f.read().strip())
                cgroup_limit_gb = val / (1024**3) if val < 2**62 else -1
            with open("/sys/fs/cgroup/memory/memory.usage_in_bytes", "r") as f:
                cgroup_usage_gb = int(f.read().strip()) / (1024**3)
        except Exception:
            pass
    except Exception:
        pass

    gpu_used_gb = gpu_total_gb = gpu_reserved_gb = -1
    gpu_dev_name = "N/A"
    gpu_processes = "N/A"
    try:
        import torch
        if torch.cuda.is_available():
            gpu_used_gb = torch.cuda.memory_allocated() / (1024**3)
            gpu_reserved_gb = torch.cuda.memory_reserved() / (1024**3)
            props = torch.cuda.get_device_properties(0)
            gpu_total_gb = props.total_mem / (1024**3)
            gpu_dev_name = props.name
    except Exception:
        pass

    try:
        import subprocess
        # Query processes on the specific GPU(s) visible to this worker
        nvsmi_cmd = ["nvidia-smi", "--query-compute-apps=pid,gpu_uuid,used_memory", "--format=csv,noheader,nounits"]
        result = subprocess.run(nvsmi_cmd, capture_output=True, text=True, timeout=5)
        if result.returncode == 0 and result.stdout.strip():
            gpu_processes = result.stdout.strip().replace("\n", " | ")
    except Exception:
        pass

    print(
        f"[SIMDIAG] [{step_name}] clip={clip_id} | "
        f"node={hostname} pid={pid} CUDA_VISIBLE_DEVICES={cuda_visible} | "
        f"RAM: {rss_gb:.1f}GB(self) {sys_avail_gb:.1f}GB/{sys_total_gb:.1f}GB(avail/total) {sys_percent}% | "
        f"cgroup: {cgroup_usage_gb:.1f}GB/{cgroup_limit_gb:.1f}GB(usage/limit) | "
        f"GPU[{gpu_dev_name}]: {gpu_used_gb:.2f}GB/{gpu_total_gb:.1f}GB(alloc/total) reserved={gpu_reserved_gb:.2f}GB | "
        f"GPU_procs: {gpu_processes} | CPU: {cpu_percent}%",
        flush=True
    )

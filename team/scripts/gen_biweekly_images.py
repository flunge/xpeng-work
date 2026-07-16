#!/usr/bin/env python3
"""生成 GIC 双周报 4 张配图（GPT-Image-2 via SoCheap API）。
key 从 pipelines/media_key.txt 读取（脚本运行时读，不经过对话上下文）。
图存到 scripts/.tmp/ 下（临时产物，贴飞书后即弃），文件名 biweekly_0630_<topic>.png
"""

import json
import os
import re
import sys
import time
import urllib.request

KEY_FILE = "/workspace/team/pipelines/media_key.txt"
OUT_DIR = "/workspace/team/tmp"
API_URL = "https://socheap.ai/media/generations"

# 每张图：高信息密度的项目仪表盘，中文，承载本组两周算法/技术进展细节
# ⚠️ prompt 数据必须与清洗后双周报正文一致（2026-06-30 重写）：
# 已剔除非本组内容(4728/182模型/620/召回10)、旧数据(极速2.6×/近1500/一致性14%/1000工作台)、
# 脑补(deepseek-v4/83.3%)、非正式来源(斑马车衣/pitch1°)、黑话(塔包)。改图前先跑 check_report.py 对齐正文。
IMAGES = {
    "topic1_3dgs_production": (
        "信息图风格的项目进展仪表盘，主题「3DGS 生产链路：长里程量产 + 1 小时极速」，深色科技蓝背景，左右分栏布局。"
        "左栏「RC 长里程」：截至 6/30 新数据累计 561.5km，undistort 多进程 timeout 根因已修，"
        "公共卡池被高优任务抢占、日产难稳定保 100km（私有卡池并发仅约 40 是瓶颈），7/1 用新老数据混合先凑 1000km，长里程看板 7/13 上线。"
        "右栏「极速模式」：UCP 全链路约 100 分钟跑通，复现率 108 个 case 复现 80 个、按全量折损后约 50% 作为可用基线，"
        "6/26 对外交付文档完成，仿真设置参数已精简至 1 个、自适应方案调研中。"
        "用进度条、KPI 数字块、箭头呈现。中文标注，填满整个画面，无白边。"
    ),
    "topic2_sil_algorithm": (
        "信息图风格的算法迭代仪表盘，主题「闭环仿真 SIL：渲染算法迭代 + 图像质检」，深色科技蓝背景，三栏布局。"
        "① NVFixer 渲染：带 ref 图新版 TRT 模型渲染效率比 1:7.2（旧未优化 1:6.5、Difix 1:17），TRT 与 PyTorch 输出对齐；"
        "新架构 V3C（DIT 全局 self-attention 拼接 ref+render latent，+8dB PSNR）/ V3D（VAE decoder 后注入 ref，+6dB PSNR），"
        "64 卡全量训练、test set 最高 PSNR 31；PTQ 量化触天花板 → 转 TinyVAE/LightVAE 蒸馏。"
        "② CLIP-IQA 图像质检 6/26 接入 SIL 链路、过滤极差渲染 case。"
        "③ 车型泛化：多车型 Pipeline 上线，三参数（车衣/外参 pitch+roll/车型）敏感性扫描方案；"
        "红绿灯验证——3DGS 直出对变灯瞬间学不好、叠加 diffusion 后明显变好。"
        "用对比柱状图、架构箭头、PSNR 提升曲线呈现。中文标注，填满画面，无白边。"
    ),
    "topic3_hil": (
        "信息图风格的验收仪表盘，主题「闭环仿真 HIL：阶段性验收」，深色科技蓝背景。"
        "核心数据：6/29 完成实时模式阶段性验收，5 个台架节点机房部署可用，3 节点跑 1300+ scenario 无中断，"
        "效率比 batch=20 为 1:2.82、batch≥30 达 1:2.5（达成月目标 1:3），数据可用性 100%（5% 丢帧阈值）；"
        "PAT 评测链路已打通、跑通两版本模型对比；慢速模式带 ref 图链路把 H265 经 NVFixer VAE encoder 重刷成 latent、代码适配 50%。"
        "底部风险：6 月底每天 1000 scenario 全跑目标未达，5080 台架采购延至 7 月底/8 月初，节点规模化是 Q3 瓶颈。"
        "用环形进度图、KPI 数字块、节点拓扑呈现。中文标注，填满画面，无白边。"
    ),
    "topic4_agent": (
        "信息图风格的 AI Agent 进展仪表盘，主题「AI Agent 重塑研发·生产·评测流」，深色科技蓝背景，右上角「首次汇报」徽章。"
        "三类 Agent：① 复现率 Agent：累计支持 11 类问题场景，道内画龙测试集准确率 80%+ 达上线标准、"
        "生产验收复现正确率 89%、摆动复现 19/24（79%），FM 提示词复现流程已集成、40 验证集准确率 80%；"
        "② 闭环 Diff Agent：6 个 metric 自动 diff（准确率 50% 迭代中）、道内画龙 Topdiff 7/11 正确上报、AB Review 质检报告 demo；"
        "③ Prompt 对齐 Agent：人工一致率 85%（提示词开关 + 飞书机器人 HTML 输出已解决）；"
        "④ 环境构建 Agent：输入 base image 自动产出 Dockerfile。用流程箭头、准确率进度条、Agent 图标呈现。"
        "中文标注，填满整个画面，无白边。"
    ),
}


def read_key():
    """从文件里正则提取 sk- 开头的 key（文件实际是 curl 示例文档）。"""
    with open(KEY_FILE) as f:
        content = f.read()
    m = re.search(r'sk-[A-Za-z0-9]+', content)
    if not m:
        # 文件本身就是纯 key 的情况
        s = content.strip()
        return s if s else None
    return m.group(0)


def _post(url, key, body):
    req = urllib.request.Request(
        url, data=json.dumps(body).encode(),
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        err_body = e.read().decode("utf-8", "ignore")
        print(f"    HTTP {e.code} 响应体: {err_body[:500]}")
        raise


def _get(url, key):
    req = urllib.request.Request(
        url, headers={"Authorization": f"Bearer {key}"}, method="GET",
    )
    with urllib.request.urlopen(req, timeout=120) as resp:
        return json.loads(resp.read())


def _extract_url(data):
    """从任意层级里找出图片 url。"""
    if isinstance(data, dict):
        for k in ("url", "image_url", "output_url", "result_url"):
            if isinstance(data.get(k), str) and data[k].startswith("http"):
                return data[k]
        for v in data.values():
            r = _extract_url(v)
            if r:
                return r
    elif isinstance(data, list):
        for v in data:
            r = _extract_url(v)
            if r:
                return r
    return None


def gen_one(key, name, prompt):
    # 1. 创建生成任务
    create = _post(API_URL, key, {
        "model": "gpt-image-2",
        "prompt": prompt,
        "size": "1024x576",
    })
    gen_id = create.get("id") or create.get("generation_id") or (create.get("data") or {}).get("id")
    # 可能直接同步返回了图
    url = _extract_url(create)
    status = (create.get("status") or "").lower()

    # 2. 异步则轮询
    if not url and gen_id:
        poll_url = f"{API_URL}/{gen_id}"
        for _ in range(40):  # 最多轮询 ~3 分钟
            time.sleep(5)
            st = _get(poll_url, key)
            status = (st.get("status") or "").lower()
            url = _extract_url(st)
            if url:
                break
            if status in ("failed", "error", "canceled", "cancelled"):
                print(f"  [{name}] 任务失败 status={status}: {json.dumps(st)[:200]}")
                return False

    if not url:
        print(f"  [{name}] 无图片 url，create 返回: {json.dumps(create)[:300]}")
        return False

    out_path = os.path.join(OUT_DIR, f"biweekly_0630_{name}.png")
    urllib.request.urlretrieve(url, out_path)
    print(f"  [{name}] OK -> {out_path}")
    return True


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    key = read_key()
    if not key:
        print("ERROR: empty key")
        sys.exit(1)
    print(f"Key loaded ({len(key)} chars). 生成 {len(IMAGES)} 张图...")
    for name, prompt in IMAGES.items():
        print(f"生成 {name} ...")
        try:
            gen_one(key, name, prompt)
        except Exception as e:
            print(f"  [{name}] FAILED: {e}")
        time.sleep(2)
    print("Done.")


if __name__ == "__main__":
    main()

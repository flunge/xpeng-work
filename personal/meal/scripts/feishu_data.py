#!/usr/bin/env python3
"""飞书数据层：meal 全量迁飞书后，脚本经此模块从飞书 Base / 云盘读写。

设计要点：
- 配方以「原始YAML」列无损存于 Base，本模块读回后 yaml.safe_load 还原为脚本
  原本从本地 *.yaml 得到的同构 dict，故上层 load_all_recipes 接口保持不变。
- config（family/holidays/vacations）从飞书「配置与规则」文件夹按需拉取到本地缓存。
- 依赖命令行 lark-cli（与仓库其他飞书脚本一致），不额外引入 SDK。
"""
import os
import json
import subprocess
import yaml
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
_FEISHU_CFG = None
_CACHE_DIR = BASE_DIR / ".feishu_cache"


def _cfg():
    global _FEISHU_CFG
    if _FEISHU_CFG is None:
        with open(BASE_DIR / "config" / "feishu.yaml", encoding="utf-8") as f:
            _FEISHU_CFG = yaml.safe_load(f)
    return _FEISHU_CFG


def _lark_json(args, cwd=None):
    """运行 lark-cli 并解析 JSON（跳过可能的前置非 JSON 行）。"""
    r = subprocess.run(["lark-cli"] + args, capture_output=True, text=True, cwd=cwd)
    out = r.stdout
    i = out.find("{")
    if i < 0:
        raise RuntimeError(f"lark-cli 无 JSON 输出: {args}\nstderr: {r.stderr[:300]}")
    return json.loads(out[i:])


# ---------- 配方（从 Base 读原始YAML还原）----------

def _fetch_all_records():
    """分页拉取配方表全部记录，返回 (fields, rows)。"""
    rb = _cfg()["recipe_base"]
    base, table = rb["app_token"], rb["table_id"]
    fields = None
    rows = []
    offset = 0
    while True:
        d = _lark_json(["base", "+record-list", "--base-token", base,
                        "--table-id", table, "--limit", "200",
                        "--offset", str(offset), "--format", "json"])["data"]
        fields = d["fields"]
        rows += d["data"]
        ids = d["record_id_list"]
        if d.get("has_more") and ids:
            offset += len(ids)
        else:
            break
    return fields, rows


_RECIPE_CACHE = None


def _all_recipes():
    """还原全部配方为 {type: [recipe_dict, ...]}，带进程内缓存。"""
    global _RECIPE_CACHE
    if _RECIPE_CACHE is not None:
        return _RECIPE_CACHE
    rb = _cfg()["recipe_base"]
    fields, rows = _fetch_all_records()
    raw_i = fields.index(rb["raw_field"])
    src_i = fields.index(rb["source_field"])
    by_type = {}
    for r in rows:
        raw = r[raw_i]
        if not raw:
            continue
        recipe = yaml.safe_load(raw)
        recipe["_file"] = os.path.basename(r[src_i]) if r[src_i] else ""
        recipe["_type"] = recipe.get("type", "")
        by_type.setdefault(recipe["_type"], []).append(recipe)
    # 保持与本地 glob(sorted) 一致的顺序
    for t in by_type:
        by_type[t].sort(key=lambda x: x.get("_file", ""))
    _RECIPE_CACHE = by_type
    return by_type


def load_all_recipes(recipe_type):
    """从飞书 Base 加载某一类型的全部配方（替代本地 recipes/<type>/*.yaml）。"""
    return list(_all_recipes().get(recipe_type, []))


# ---------- config（从飞书「配置与规则」拉取缓存）----------

_CACHE_REL = ".feishu_cache"  # 相对 BASE_DIR


def _ensure_config_cached():
    """把「配置与规则」文件夹镜像到本地缓存目录，供 load_config 读取。

    +pull/+push 的 --local-dir 相对 cwd，故统一以 BASE_DIR 为 cwd、传相对路径。
    """
    folder = _cfg()["folders"]["配置与规则"]
    _CACHE_DIR.mkdir(exist_ok=True)
    _lark_json(["drive", "+pull", "--folder-token", folder,
                "--local-dir", _CACHE_REL, "--format", "json"], cwd=str(BASE_DIR))


def load_config(name):
    """加载 config yaml（如 family.yaml / holidays-2026.yaml），从飞书缓存读取。"""
    path = _CACHE_DIR / name
    if not path.exists():
        _ensure_config_cached()
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


# ---------- 每日菜谱 / 月计划（上传到飞书云盘）----------

def _rel_to_base(local_dir):
    """把本地目录转成相对 BASE_DIR 的路径（+push 要求相对 cwd）。"""
    return os.path.relpath(str(local_dir), str(BASE_DIR))


def upload_daily(local_dir):
    """把本地生成的每日菜谱 md 推送到飞书「每日菜谱」文件夹。"""
    folder = _cfg()["folders"]["每日菜谱"]
    return _lark_json(["drive", "+push", "--local-dir", _rel_to_base(local_dir),
                       "--folder-token", folder, "--if-exists", "overwrite",
                       "--format", "json"], cwd=str(BASE_DIR))


def upload_plans(local_dir):
    """把本地生成的月计划 md 推送到飞书「月度计划」文件夹。"""
    folder = _cfg()["folders"]["月度计划"]
    return _lark_json(["drive", "+push", "--local-dir", _rel_to_base(local_dir),
                       "--folder-token", folder, "--if-exists", "overwrite",
                       "--format", "json"], cwd=str(BASE_DIR))


def fetch_daily_card(date_str):
    """从飞书「每日菜谱」下载指定日期(YYYY-MM-DD)的卡片 md，返回文本；不存在返回 None。"""
    folder = _cfg()["folders"]["每日菜谱"]
    d = _lark_json(["api", "GET", "/open-apis/drive/v1/files",
                    "--params", json.dumps({"folder_token": folder}),
                    "--format", "json"])
    fname = f"{date_str}.md"
    tok = None
    for f in d.get("data", {}).get("files", []):
        if f.get("name") == fname:
            tok = f.get("token")
            break
    if not tok:
        return None
    _CACHE_DIR.mkdir(exist_ok=True)
    p = _CACHE_DIR / fname
    rel = os.path.join(_CACHE_REL, fname)
    _lark_json(["drive", "+download", "--file-token", tok,
                "--output", rel, "--overwrite", "--format", "json"], cwd=str(BASE_DIR))
    if p.exists():
        return p.read_text(encoding="utf-8")
    return None


if __name__ == "__main__":
    # 自检：打印各类型配方数量
    tot = 0
    for t in ["breakfast", "lunch", "dinner", "side", "lunch_quick", "special"]:
        n = len(load_all_recipes(t))
        tot += n
        print(f"{t}: {n}")
    print(f"合计: {tot}")

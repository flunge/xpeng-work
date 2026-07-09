"""全局仿真开关注册表（单一数据源）。

平台 rerun_e2e_job 的闭环开关编码在 fuyao_config.manual_sim_configuration 字段里，
是一个逗号分隔的字符串，混合两种 token 形式（已抓真实任务校准）：

  1. 命名空间式：``<namespace>@<key>:1``，如 ``simulation@perfect_control:1``
  2. 环境标志式：``<KEY>=true``，如 ``USE_NVFIXER=true``

为避免使用方记忆冗长的完整 token，这里建立「简称 → 完整 token」的查表：
用户在 CLI / API 只需用简称（如 ``perfect_control`` / ``use_nvfixer``）打开开关，
提交时由 :func:`build_manual_sim_configuration` 查表展开为平台所需的完整字符串。

注册表是开关相关逻辑的唯一来源：``constants.SWITCH_WHITELIST`` 也由它派生，
新增/调整开关只需改这一处。
"""
from __future__ import annotations

# 简称 → 平台完整 token（"打开"形态）。
# dict 保持插入顺序 → 拼装输出顺序稳定（便于幂等键与排查）。
SWITCH_REGISTRY: dict[str, str] = {
    # —— 命名空间式（manual_sim_configuration 内 "ns@key:1"）——
    "perfect_control":          "simulation@perfect_control:1",
    "use_difix_reference":      "simworld@use_difix_reference:1",
    "enable_inplace_rendering": "simworld@enable_inplace_rendering:1",
    "use_difix_tensorrt":       "simworld@use_difix_tensorrt:1",
    "render_original_png":      "simworld@render_original_png:1",
    "use_difix":                "simworld@use_difix:1",
    # —— 环境标志式（"KEY=true"）——
    "use_nvfixer":                "USE_NVFIXER=true",
    "use_nvfixer_tensorrt_noref": "USE_NVFIXER_TENSORRT_NOREF=true",
    "use_nvfixer_tensorrt_ref":   "USE_NVFIXER_TENSORRT_REF=true",
    "use_nvfixer_reference":      "USE_NVFIXER_REFERENCE=true",
}

# 稳定顺序的简称元组，供白名单/帮助文案复用。
SWITCH_ALIASES: tuple[str, ...] = tuple(SWITCH_REGISTRY)


def is_known(alias: str) -> bool:
    """是否为已注册的开关简称。"""
    return alias in SWITCH_REGISTRY


def build_manual_sim_configuration(switches: dict | None) -> str:
    """把开关 dict 查表拼成平台 manual_sim_configuration 字符串。

    - 已注册简称 → 展开为完整 token（按注册表顺序，仅收录"打开"的开关）。
    - 兼容直传完整 token 的键（含 ``@`` 或 ``=``），原样保留，便于显式覆盖。
    - 关闭（值为假）的开关一律省略，与平台真实行为一致（未列出即默认关闭）。
    """
    s = switches or {}
    tokens: list[str] = []

    # 1) 已知简称 → 规范 token，按注册表固定顺序输出
    for alias, token in SWITCH_REGISTRY.items():
        if s.get(alias):
            tokens.append(token)

    # 2) 兼容直传完整 token 的键（非注册简称且含 '@' / '='）
    for key, on in s.items():
        if not on or key in SWITCH_REGISTRY:
            continue
        if "@" in key or "=" in key:
            # 命名空间键缺省补 ":1"；已带值或环境标志式则原样保留
            tokens.append(key if (":" in key or "=" in key) else f"{key}:1")

    return ",".join(tokens)

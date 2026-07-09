import pytest
from tse.switches import (
    SWITCH_REGISTRY, SWITCH_ALIASES, is_known, build_manual_sim_configuration,
)
from tse.constants import SWITCH_WHITELIST


def test_whitelist_derived_from_registry():
    # 白名单与注册表简称严格一致（单一数据源）
    assert SWITCH_WHITELIST == frozenset(SWITCH_ALIASES)
    assert set(SWITCH_WHITELIST) == set(SWITCH_REGISTRY)


def test_is_known():
    assert is_known("use_difix")
    assert is_known("use_nvfixer")
    assert not is_known("nonexistent")
    assert not is_known("simworld@use_difix")  # 完整 token 不是简称


def test_build_expands_aliases_in_canonical_order():
    # 无论传入顺序如何，输出按注册表固定顺序
    out = build_manual_sim_configuration(
        {"use_difix": True, "perfect_control": True, "use_nvfixer": True})
    assert out == (
        "simulation@perfect_control:1,"
        "simworld@use_difix:1,"
        "USE_NVFIXER=true"
    )


def test_build_omits_disabled_switches():
    out = build_manual_sim_configuration({"use_difix": True, "perfect_control": False})
    assert out == "simworld@use_difix:1"


def test_build_empty_or_none():
    assert build_manual_sim_configuration(None) == ""
    assert build_manual_sim_configuration({}) == ""
    assert build_manual_sim_configuration({"use_difix": False}) == ""


def test_build_full_set_matches_platform_string():
    # 全开 → 与用户提供的真实「全部可能开关」字符串一致
    all_on = {alias: True for alias in SWITCH_ALIASES}
    expected = (
        "simulation@perfect_control:1,"
        "simworld@use_difix_reference:1,"
        "simworld@enable_inplace_rendering:1,"
        "simworld@use_difix_tensorrt:1,"
        "simworld@render_original_png:1,"
        "simworld@use_difix:1,"
        "USE_NVFIXER=true,"
        "USE_NVFIXER_TENSORRT_NOREF=true,"
        "USE_NVFIXER_TENSORRT_REF=true,"
        "USE_NVFIXER_REFERENCE=true"
    )
    assert build_manual_sim_configuration(all_on) == expected


def test_build_passthrough_full_token():
    # 兼容直传完整 token（命名空间键自动补 :1）
    out = build_manual_sim_configuration({"foo@bar": True})
    assert out == "foo@bar:1"
    out2 = build_manual_sim_configuration({"CUSTOM_ENV=true": True})
    assert out2 == "CUSTOM_ENV=true"

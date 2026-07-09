"""集中式错误码定义与异常分类。

背景
----
后端在捕获 ``gpu_processor`` / ``pre_processor`` 抛出的异常时，只会把异常的
字符串（``str(e)``）记录到“失败详情”里，并且后端代码不允许改动。

方案
----
我们在自己的代码里把原始异常重新包装成 :class:`ClassifiedPipelineError`，
让它的 ``str()`` 直接输出结构化的 key-value（JSON）信息，于是在 **不修改后端**
的前提下，后端记录下来的字符串就同时包含：

* ``error_id``      —— 错误ID（数字，便于机器归类）
* ``error_type``    —— 错误类型（中文可读标签）
* ``error_message`` —— 原始异常的简短消息
* ``error_detail``  —— 完整错误详情（traceback 全文）

错误定义表
----------
错误类型 / 错误ID / 匹配关键字 全部从 **YAML 配置文件**读取，默认路径为
``pipeline/configs/error_definitions.yaml``，可用环境变量
``PIPELINE_ERROR_DEFINITIONS_PATH`` 覆盖。

YAML 结构（顶层 ``errors`` 为列表，每条）：
* ``error_id``   —— 唯一错误ID
* ``error_type`` —— 中文可读的错误类型标签
* ``match``      —— 匹配关键字列表，任意一个出现在异常消息里即命中

新增错误类型时，只需在该 YAML 里加一条即可，无需改动代码。
"""

import json
import os
import traceback

import yaml


# 未命中任何已知错误时使用的兜底分类
UNKNOWN_ERROR_ID = 999999
UNKNOWN_ERROR_TYPE = "未知错误"

# 配置文件默认路径（pipeline/configs/error_definitions.yaml），可用环境变量覆盖
_DEFAULT_DEFINITIONS_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "configs", "error_definitions.yaml"
)
ERROR_DEFINITIONS_PATH = os.environ.get(
    "PIPELINE_ERROR_DEFINITIONS_PATH", _DEFAULT_DEFINITIONS_PATH
)


def _load_error_definitions(path=None):
    """从 YAML 配置文件读取错误定义。

    任何读取/解析失败都不会抛出（避免拖垮主流程），失败时返回空表，
    后续所有错误都会归入兜底分类（``未知错误`` / ``999999``）。
    """
    path = path or ERROR_DEFINITIONS_PATH
    definitions = []
    try:
        with open(path, "r", encoding="utf-8") as fp:
            data = yaml.safe_load(fp) or {}
        # 兼容两种写法：顶层 {"errors": [...]} 或顶层直接是列表
        rows = data.get("errors", []) if isinstance(data, dict) else data
        for row in rows or []:
            if not isinstance(row, dict):
                continue
            error_id = row.get("error_id")
            error_type = row.get("error_type")
            if error_id is None or not error_type:
                continue
            raw_match = row.get("match", [])
            if isinstance(raw_match, str):
                raw_match = [raw_match]
            patterns = [str(p).strip() for p in (raw_match or []) if str(p).strip()]
            definitions.append(
                {
                    "error_id": error_id,
                    "error_type": str(error_type).strip(),
                    "match": patterns,
                }
            )
    except FileNotFoundError:
        print(f"[WARN] error definitions file not found: {path}, all errors fall back to unknown")
    except Exception as exc:  # noqa: BLE001 - 配置问题绝不能拖垮主流程
        print(f"[WARN] failed to load error definitions from {path}: {exc}")
    return definitions


def reload_error_definitions(path=None):
    """重新加载错误定义表（修改 CSV 后无需重启即可生效）。"""
    global ERROR_DEFINITIONS
    ERROR_DEFINITIONS = _load_error_definitions(path)
    return ERROR_DEFINITIONS


# 模块导入时加载一次
ERROR_DEFINITIONS = _load_error_definitions()


class ClassifiedPipelineError(Exception):
    """带错误类型 / 错误ID 的结构化异常。

    其 ``str()`` / ``args[0]`` 均为结构化 JSON 字符串，因此无论后端用
    ``str(e)``、``f"{e}"`` 还是 ``e.args`` 记录，拿到的都是完整结构化信息。
    """

    def __init__(self, error_id, error_type, error_message, error_detail):
        self.error_id = error_id
        self.error_type = error_type
        self.error_message = error_message
        self.error_detail = error_detail
        # 字段顺序固定为：error_type 最前 -> error_id 居中 -> 栈(error_detail)最后。
        # Python 3.7+ 的 dict 与 json.dumps 均保留插入顺序。
        payload = {
            "error_type": error_type,
            "error_id": error_id,
            "error_message": error_message,
            "error_detail": error_detail,
        }
        # ensure_ascii=False 保证中文在记录里可读
        super().__init__(json.dumps(payload, ensure_ascii=False))

    def to_dict(self):
        return {
            "error_type": self.error_type,
            "error_id": self.error_id,
            "error_message": self.error_message,
            "error_detail": self.error_detail,
        }


def _match_error(message):
    """根据异常消息匹配错误ID与错误类型，未命中返回兜底分类。"""
    for definition in ERROR_DEFINITIONS:
        patterns = definition.get("match", [])
        if isinstance(patterns, str):
            patterns = [patterns]
        for pattern in patterns:
            if pattern and pattern in message:
                return definition["error_id"], definition["error_type"]
    return UNKNOWN_ERROR_ID, UNKNOWN_ERROR_TYPE


def classify_error(exc, error_detail=None):
    """把任意异常分类并包装成 :class:`ClassifiedPipelineError`。

    必须在 ``except`` 代码块内调用，以便 ``traceback.format_exc()`` 能抓到当前异常。
    若 ``exc`` 已经是 :class:`ClassifiedPipelineError`，则原样返回（幂等，避免重复包装）。
    """
    if isinstance(exc, ClassifiedPipelineError):
        return exc

    message = str(exc)
    if error_detail is None:
        error_detail = traceback.format_exc()
    error_id, error_type = _match_error(message)
    return ClassifiedPipelineError(
        error_id=error_id,
        error_type=error_type,
        error_message=message,
        error_detail=error_detail,
    )

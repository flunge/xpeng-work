class RequestValidationError(ValueError):
    """用户输入非法，CLI 直接报错，不进入工作流。"""


class NonRetryableBuildError(Exception):
    """分支不存在 / 编译错误等代码问题，编包重试无意义。"""

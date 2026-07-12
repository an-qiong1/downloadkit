"""
自定义异常模块
"""

class PauseException(Exception):
    """下载暂停异常"""
    pass


class CancelException(Exception):
    """下载取消异常"""
    pass

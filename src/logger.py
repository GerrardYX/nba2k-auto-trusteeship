"""
logger.py - 日志与异常截图
提供统一的日志输出(控制台彩色 + 文件),出错时自动截图存档。
"""
import logging
import os
import sys
import time
from datetime import datetime

try:
    import yaml
except ImportError:
    yaml = None


class ColorFormatter(logging.Formatter):
    """控制台彩色输出"""
    COLORS = {
        "DEBUG": "\033[36m",     # cyan
        "INFO": "\033[32m",      # green
        "WARNING": "\033[33m",   # yellow
        "ERROR": "\033[31m",     # red
        "CRITICAL": "\033[35m",  # magenta
    }
    RESET = "\033[0m"

    def format(self, record):
        color = self.COLORS.get(record.levelname, "")
        record.msg = f"{color}{record.msg}{self.RESET}"
        return super().format(record)


class Logger:
    """全局日志管理器(单例风格)"""

    _instance = None
    _screenshot_func = None  # 注入的截图函数

    @classmethod
    def setup(cls, config_path="config/settings.yaml"):
        if cls._instance is not None:
            return cls._instance

        # 读取配置
        level_str = "INFO"
        log_file = "logs/run.log"
        color = True
        if yaml and os.path.exists(config_path):
            with open(config_path, "r", encoding="utf-8") as f:
                cfg = yaml.safe_load(f) or {}
            lc = cfg.get("logging", {})
            level_str = lc.get("level", "INFO")
            log_file = lc.get("file", "logs/run.log")
            color = lc.get("console_color", True)

        os.makedirs(os.path.dirname(log_file) or ".", exist_ok=True)

        level = getattr(logging, level_str.upper(), logging.INFO)
        logger = logging.getLogger("nba2k")
        logger.setLevel(level)
        logger.handlers.clear()

        fmt = "%(asctime)s [%(levelname)-7s] %(message)s"
        datefmt = "%H:%M:%S"

        # 文件
        fh = logging.FileHandler(log_file, encoding="utf-8")
        fh.setFormatter(logging.Formatter(fmt, datefmt))
        logger.addHandler(fh)

        # 控制台
        sh = logging.StreamHandler(sys.stdout)
        if color:
            sh.setFormatter(ColorFormatter(fmt, datefmt))
        else:
            sh.setFormatter(logging.Formatter(fmt, datefmt))
        logger.addHandler(sh)

        cls._instance = logger
        return logger

    @classmethod
    def get(cls):
        if cls._instance is None:
            cls.setup()
        return cls._instance

    @classmethod
    def set_screenshot_func(cls, func):
        """注入截图函数,用于出错时自动存档"""
        cls._screenshot_func = func

    @classmethod
    def screenshot(cls, tag="error"):
        """调用注入的截图函数保存截图"""
        if cls._screenshot_func:
            try:
                ts = datetime.now().strftime("%Y%m%d_%H%M%S")
                path = f"logs/screenshot_{tag}_{ts}.png"
                cls._screenshot_func(path)
                cls.get().info(f"截图已保存: {path}")
                return path
            except Exception as e:
                cls.get().warning(f"截图失败: {e}")
        return None


def get_logger():
    return Logger.get()

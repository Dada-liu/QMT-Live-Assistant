"""日志系统。

提供控制台与文件日志处理器，支持按日轮转。
"""
import logging
import os
import re
from datetime import date

formatter = logging.Formatter(
    '[%(levelname)s][%(asctime)s]%(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)


class RemoveAnsiEscapeCodes(logging.Filter):
    def filter(self, record):
        record.msg = re.sub(r'\033\[[0-9;]*m', '', str(record.msg))
        return True


def create_logger(name="qmt-"):
    logger = logging.getLogger(name)
    logger.setLevel(logging.DEBUG)

    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(formatter)
    logger.addHandler(stream_handler)

    log_dir = 'logs'
    if not os.path.exists(log_dir):
        os.makedirs(log_dir)

    file_handler = logging.FileHandler(
        f"{log_dir}/{date.today().strftime('%Y-%m-%d')}.log",
        encoding='utf-8'
    )
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(formatter)
    file_handler.addFilter(RemoveAnsiEscapeCodes())
    logger.addHandler(file_handler)

    return logger


logger = create_logger()

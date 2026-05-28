import logging
import requests
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


class WeChatHandler(logging.Handler):
    def __init__(self, webhook_url):
        super().__init__()
        self.webhook_url = webhook_url

    def emit(self, record):
        log_entry = self.format(record)
        payload = {
            "msgtype": "text",
            "text": {
                "content": log_entry
            }
        }
        try:
            response = requests.post(self.webhook_url, json=payload)
            response.raise_for_status()
        except requests.exceptions.RequestException as e:
            print(f"Failed to send log to WeChat: {e}")


def add_wechat_handler(logger, level, wechat_webhook_url):
    if wechat_webhook_url is not None:
        wechat_handler = WeChatHandler(wechat_webhook_url)
        wechat_handler.setLevel(level or logging.INFO)
        wechat_handler.setFormatter(formatter)
        wechat_handler.addFilter(RemoveAnsiEscapeCodes())
        logger.addHandler(wechat_handler)


logger = create_logger()

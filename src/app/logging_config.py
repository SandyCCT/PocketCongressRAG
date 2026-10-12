"""集中設定 PocketCongressRAG 的 console-first 日誌。"""

import logging
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path

import app.config as config


LOGGER_NAME = "pocket_congress"
_HANDLER_MARKER = "_pocket_congress_handler"


class DirectoryCreatingTimedRotatingFileHandler(TimedRotatingFileHandler):
    """寫入前確保 log 目錄存在，避免執行期間目錄被移除後無法記錄。"""

    def emit(self, record: logging.LogRecord) -> None:
        Path(self.baseFilename).parent.mkdir(parents=True, exist_ok=True)
        super().emit(record)


def configure_logging(
    *,
    log_dir: str | Path | None = None,
    log_level: str | None = None,
    retention_days: int | None = None,
    file_logging_enabled: bool | None = None,
) -> logging.Logger:
    """設定 console-first logger；需要時才加入每日輪替檔案 handler。"""
    logger = logging.getLogger(LOGGER_NAME)
    level_name = (log_level or config.LOG_LEVEL).upper()
    level = logging.getLevelNamesMapping().get(level_name)
    if level is None:
        raise ValueError(f"不支援的 LOG_LEVEL：{level_name}")

    enable_file = (
        file_logging_enabled
        if file_logging_enabled is not None
        else config.LOG_FILE_ENABLED
    )
    days = retention_days if retention_days is not None else config.LOG_RETENTION_DAYS
    if enable_file and days < 1:
        raise ValueError("LOG_RETENTION_DAYS 必須大於等於 1")

    logger.setLevel(level)
    logger.propagate = False
    if any(getattr(handler, _HANDLER_MARKER, False) for handler in logger.handlers):
        return logger

    formatter = logging.Formatter(
        "%(asctime)s | %(levelname)s | %(name)s | %(message)s"
    )

    console_handler = logging.StreamHandler()
    console_handler.setLevel(level)
    console_handler.setFormatter(formatter)
    setattr(console_handler, _HANDLER_MARKER, True)
    logger.addHandler(console_handler)

    if enable_file:
        target_dir = Path(log_dir or config.LOG_DIR)
        target_dir.mkdir(parents=True, exist_ok=True)
        file_handler = DirectoryCreatingTimedRotatingFileHandler(
            target_dir / "pocket_congress.log",
            when="midnight",
            interval=1,
            backupCount=days,
            encoding="utf-8",
            delay=True,
        )
        file_handler.setLevel(level)
        file_handler.setFormatter(formatter)
        file_handler.suffix = "%Y-%m-%d"
        setattr(file_handler, _HANDLER_MARKER, True)
        logger.addHandler(file_handler)

    return logger


def get_logger(module_name: str) -> logging.Logger:
    """取得位於 PocketCongressRAG logger namespace 下的 module logger。"""
    return logging.getLogger(f"{LOGGER_NAME}.{module_name}")

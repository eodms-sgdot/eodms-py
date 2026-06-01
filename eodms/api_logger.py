import logging
import os
from typing import Optional


LOG_DATE_FORMAT = "%Y-%m-%d %H:%M:%S %z"
LOG_MESSAGE_FORMAT = "%(asctime)s %(levelname)s %(name)s %(message)s"


def _resolve_level(level: Optional[str] = None) -> int:
    if isinstance(level, str):
        return getattr(logging, level.upper(), logging.INFO)
    return logging.INFO


def _build_formatter() -> logging.Formatter:
    return logging.Formatter(LOG_MESSAGE_FORMAT, datefmt=LOG_DATE_FORMAT)


def get_package_logger() -> logging.Logger:
    logger = logging.getLogger("eodms")
    if not logger.handlers:
        logger.addHandler(logging.NullHandler())
    return logger


def configure_logging(
    level: Optional[str] = None,
    log_file: Optional[str] = None,
    stream: bool = True,
) -> logging.Logger:
    """Explicitly configure eodms logging for wrapper applications."""
    logger = logging.getLogger("eodms")
    logger.handlers.clear()
    logger.setLevel(_resolve_level(level))
    logger.propagate = False

    formatter = _build_formatter()

    if stream:
        stream_handler = logging.StreamHandler()
        stream_handler.setLevel(logger.level)
        stream_handler.setFormatter(formatter)
        logger.addHandler(stream_handler)

    if log_file:
        log_dir = os.path.dirname(log_file)
        if log_dir:
            os.makedirs(log_dir, exist_ok=True)
        file_handler = logging.FileHandler(log_file, encoding="utf-8")
        file_handler.setLevel(logger.level)
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)

    if not logger.handlers:
        logger.addHandler(logging.NullHandler())

    return logger


def get_logger(name: str) -> logging.Logger:
    get_package_logger()
    return logging.getLogger(f"eodms.{name}")


eodms_logger = get_logger("core")


class EODMSLogger(logging.LoggerAdapter):
    """Compatibility adapter retained for existing wrapper code."""

    def __init__(self, header: str, logger: logging.Logger):
        super().__init__(logger, {})

    def process(self, msg: str, kwargs):
        return msg, kwargs

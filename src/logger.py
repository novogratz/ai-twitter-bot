"""Centralized logging configuration for the bot."""
import logging
import os
import sys
from logging.handlers import RotatingFileHandler
from .config import _PROJECT_ROOT

LOG_FILE = os.path.join(_PROJECT_ROOT, "bot.log")


def setup_logging(level: str = "INFO") -> logging.Logger:
    """Configure structured logging with rotation. Returns root logger."""
    logger = logging.getLogger("bot")
    logger.setLevel(getattr(logging, level.upper(), logging.INFO))

    fmt = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # Console handler
    console = logging.StreamHandler(sys.stdout)
    console.setFormatter(fmt)
    logger.addHandler(console)

    # Rotating file handler (5MB max, keep 3 backups)
    file_handler = RotatingFileHandler(
        LOG_FILE, maxBytes=5 * 1024 * 1024, backupCount=3,
    )
    file_handler.setFormatter(fmt)
    logger.addHandler(file_handler)

    return logger


log = setup_logging()

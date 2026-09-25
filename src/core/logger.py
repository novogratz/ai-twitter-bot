"""Centralized logging configuration for the bot."""
import logging
import os
import sys
from logging.handlers import RotatingFileHandler
from .settings import PROJECT_ROOT

LOG_FILE = os.path.join(PROJECT_ROOT, "bot.log")


def setup_logging(level: str = "INFO") -> logging.Logger:
    """Configure structured logging with rotation. Returns root logger."""
    logger = logging.getLogger("bot")
    logger.setLevel(getattr(logging, level.upper(), logging.INFO))
    # Prevent duplicate lines: don't propagate to root logger (APScheduler
    # or other libs may add a StreamHandler there via basicConfig).
    logger.propagate = False

    # Guard against duplicate handlers if this function is called more than once
    # (e.g. module reimport, test setup).
    if logger.handlers:
        return logger

    fmt = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # Console handler — ONLY when running interactively (a real TTY). Under
    # launchd / nohup the launchers redirect stdout into bot.log, and the
    # RotatingFileHandler below ALSO writes bot.log — so a stdout console
    # handler made every line appear TWICE in bot.log. Gating on isatty()
    # gives background runs exactly one clean copy (file handler), while
    # foreground `./bin/run.sh` still streams to the terminal.
    if sys.stdout.isatty():
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

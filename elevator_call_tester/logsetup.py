"""Logging: one file per session (attach it to a support ticket) plus the on-screen log."""

from __future__ import annotations

import logging
import queue
from datetime import datetime
from logging.handlers import QueueHandler
from pathlib import Path

from . import __version__, paths

LOGGER_NAME = "elevator_call_tester"
SCREEN_FORMAT = "%(asctime)s.%(msecs)03d %(levelname)-7s %(message)s"
FILE_FORMAT = "%(asctime)s.%(msecs)03d %(levelname)-7s %(name)s %(message)s"
MAX_LOG_FILES = 50


def _prune(directory: Path, keep: int) -> None:
    files = sorted(directory.glob("session-*.log"))
    for old in files[:-keep] if keep else files:
        try:
            old.unlink()
        except OSError:
            pass


def setup(directory: Path | None = None) -> tuple[queue.Queue, Path | None]:
    """Configure the package logger. Returns (queue the UI drains, log file path or None)."""
    logger = logging.getLogger(LOGGER_NAME)
    logger.setLevel(logging.DEBUG)
    logger.propagate = False
    for handler in list(logger.handlers):
        logger.removeHandler(handler)
        handler.close()

    records: queue.Queue = queue.Queue()
    screen = QueueHandler(records)
    screen.setLevel(logging.INFO)
    logger.addHandler(screen)

    log_file = None
    directory = directory or paths.log_dir()
    try:
        directory.mkdir(parents=True, exist_ok=True)
        _prune(directory, MAX_LOG_FILES - 1)
        log_file = directory / f"session-{datetime.now():%Y%m%d-%H%M%S}.log"
        file_handler = logging.FileHandler(log_file, encoding="utf-8")
        file_handler.setFormatter(logging.Formatter(FILE_FORMAT, "%Y-%m-%d %H:%M:%S"))
        file_handler.setLevel(logging.DEBUG)
        logger.addHandler(file_handler)
    except OSError as ex:
        log_file = None
        logger.warning("File logging disabled: %s", ex)

    logger.info("Elevator Call Tester %s", __version__)
    if log_file:
        logger.info("Session log: %s", log_file)
    return records, log_file


def screen_formatter() -> logging.Formatter:
    return logging.Formatter(SCREEN_FORMAT, "%H:%M:%S")

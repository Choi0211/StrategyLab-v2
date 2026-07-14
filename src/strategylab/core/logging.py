"""Logging setup for StrategyLab v2."""

from __future__ import annotations

import logging
from pathlib import Path


def configure_logger(
    name: str = "strategylab",
    level: str = "INFO",
    log_directory: str | Path | None = None,
) -> logging.Logger:
    """Create a logger with console output and an optional local file handler."""

    logger = logging.getLogger(name)
    logger.setLevel(_level_number(level))
    logger.handlers.clear()
    logger.propagate = False

    formatter = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")

    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(formatter)
    logger.addHandler(stream_handler)

    if log_directory is not None:
        directory = Path(log_directory)
        directory.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(directory / "strategylab.log", encoding="utf-8")
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)

    return logger


def _level_number(level: str) -> int:
    try:
        return int(getattr(logging, level.upper()))
    except AttributeError as exc:
        raise ValueError(f"Unsupported log level: {level}") from exc


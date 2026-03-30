#!/usr/bin/env python3
"""
logger.py - Shared structured logging for semantic-clawmemory
Usage:
    from logger import get_logger
    log = get_logger("memory_search")
    log.info("Search completed")
    log.error("Something failed")
"""

import logging


def get_logger(name: str = "semantic-memory") -> logging.Logger:
    """Get a configured logger instance."""
    logger = logging.getLogger(name)

    # Only configure once
    if not logger.handlers:
        handler = logging.StreamHandler()
        formatter = logging.Formatter(
            "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
            datefmt="%H:%M:%S",
        )
        handler.setFormatter(formatter)
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)

    return logger

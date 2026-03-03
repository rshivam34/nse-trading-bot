"""Logging configuration for the trading bot."""

import logging
import os
from datetime import datetime


def setup_logger(level: str = "INFO", log_file: str = "logs/trading_bot.log"):
    """Configure logging to both console and file."""
    os.makedirs(os.path.dirname(log_file), exist_ok=True)

    # Date-stamped log file
    today = datetime.now().strftime("%Y-%m-%d")
    log_path = log_file.replace(".log", f"_{today}.log")

    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
        handlers=[
            logging.StreamHandler(),                          # Console
            logging.FileHandler(log_path, encoding="utf-8"),  # File
        ],
    )

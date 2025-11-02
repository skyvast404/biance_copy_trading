"""Logging configuration for the copy trading bot."""

import os
import logging
from logging.handlers import RotatingFileHandler
from typing import Optional

from .config_loader import LoggingConfig


def setup_logging(config: Optional[LoggingConfig] = None) -> None:
    """
    Setup logging configuration.
    
    Args:
        config: Logging configuration object. If None, uses default settings.
    """
    if config is None:
        # Default configuration
        level = logging.INFO
        log_file = "logs/copy_trade.log"
        max_bytes = 10485760  # 10MB
        backup_count = 5
        console_output = True
    else:
        level = getattr(logging, config.level.upper(), logging.INFO)
        log_file = config.file
        max_bytes = config.max_bytes
        backup_count = config.backup_count
        console_output = config.console_output
    
    # Create logs directory if it doesn't exist
    log_dir = os.path.dirname(log_file)
    if log_dir and not os.path.exists(log_dir):
        os.makedirs(log_dir)
    
    # Create formatter
    formatter = logging.Formatter(
        fmt='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    
    # Setup root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(level)
    
    # Remove existing handlers
    root_logger.handlers.clear()
    
    # Add file handler with rotation
    file_handler = RotatingFileHandler(
        log_file,
        maxBytes=max_bytes,
        backupCount=backup_count,
        encoding='utf-8'
    )
    file_handler.setLevel(level)
    file_handler.setFormatter(formatter)
    root_logger.addHandler(file_handler)
    
    # Add console handler if enabled
    if console_output:
        console_handler = logging.StreamHandler()
        console_handler.setLevel(level)
        console_handler.setFormatter(formatter)
        root_logger.addHandler(console_handler)
    
    # Reduce noise from websocket library
    logging.getLogger('websocket').setLevel(logging.WARNING)
    logging.getLogger('urllib3').setLevel(logging.WARNING)
    
    logging.info("Logging configured successfully")

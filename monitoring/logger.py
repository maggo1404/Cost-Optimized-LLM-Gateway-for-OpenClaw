"""
Logging Configuration
====================

Strukturiertes Logging für das Gateway.
JSON-Format für Log-Aggregation.
"""

import os
import sys
import json
import logging
from datetime import datetime
from typing import Any


class JSONFormatter(logging.Formatter):
    """JSON formatter for structured logging."""
    
    def format(self, record: logging.LogRecord) -> str:
        log_data = {
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "module": record.module,
            "function": record.funcName,
            "line": record.lineno
        }
        
        # Add exception info if present
        if record.exc_info:
            log_data["exception"] = self.formatException(record.exc_info)
        
        # Add extra fields
        for key, value in record.__dict__.items():
            if key not in (
                'name', 'msg', 'args', 'created', 'filename', 'funcName',
                'levelname', 'levelno', 'lineno', 'module', 'msecs',
                'pathname', 'process', 'processName', 'relativeCreated',
                'stack_info', 'exc_info', 'exc_text', 'thread', 'threadName',
                'message', 'taskName'
            ):
                log_data[key] = value
        
        return json.dumps(log_data)


class ColoredFormatter(logging.Formatter):
    """Colored formatter for console output."""
    
    COLORS = {
        'DEBUG': '\033[36m',    # Cyan
        'INFO': '\033[32m',     # Green
        'WARNING': '\033[33m',  # Yellow
        'ERROR': '\033[31m',    # Red
        'CRITICAL': '\033[35m', # Magenta
    }
    RESET = '\033[0m'
    
    def format(self, record: logging.LogRecord) -> str:
        color = self.COLORS.get(record.levelname, self.RESET)
        
        # Format timestamp
        timestamp = datetime.fromtimestamp(record.created).strftime('%H:%M:%S')
        
        # Build message
        message = f"{color}{timestamp} [{record.levelname:8}]{self.RESET} {record.name}: {record.getMessage()}"
        
        # Add exception if present
        if record.exc_info:
            message += f"\n{self.formatException(record.exc_info)}"
        
        return message


def setup_logging(
    level: str = None,
    json_output: bool = None,
    log_file: str = None
):
    """
    Configure logging for the gateway.
    
    Args:
        level: Log level (DEBUG, INFO, WARNING, ERROR)
        json_output: Use JSON format (auto-detected from ENV)
        log_file: Optional file to write logs to
    """
    # Determine settings from environment
    level = level or os.getenv("LOG_LEVEL", "INFO")
    json_output = json_output if json_output is not None else os.getenv("LOG_FORMAT") == "json"
    log_file = log_file or os.getenv("LOG_FILE")
    
    # Get root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(getattr(logging, level.upper(), logging.INFO))
    
    # Clear existing handlers
    root_logger.handlers = []
    
    # Console handler
    console_handler = logging.StreamHandler(sys.stdout)
    
    if json_output:
        console_handler.setFormatter(JSONFormatter())
    else:
        console_handler.setFormatter(ColoredFormatter())
    
    root_logger.addHandler(console_handler)
    
    # File handler if specified
    if log_file:
        file_handler = logging.FileHandler(log_file)
        file_handler.setFormatter(JSONFormatter())  # Always JSON for files
        root_logger.addHandler(file_handler)
    
    # Set levels for noisy libraries
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("asyncio").setLevel(logging.WARNING)
    
    # Log startup
    logging.info(f"Logging configured: level={level}, json={json_output}, file={log_file}")


class RequestLogger:
    """Context manager for request logging."""
    
    def __init__(self, request_id: str, logger: logging.Logger = None):
        self.request_id = request_id
        self.logger = logger or logging.getLogger("request")
        self.start_time = None
    
    def __enter__(self):
        self.start_time = datetime.utcnow()
        self.logger.info(
            f"Request started",
            extra={"request_id": self.request_id}
        )
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        duration_ms = (datetime.utcnow() - self.start_time).total_seconds() * 1000
        
        if exc_type:
            self.logger.error(
                f"Request failed: {exc_val}",
                extra={
                    "request_id": self.request_id,
                    "duration_ms": round(duration_ms, 1),
                    "error": str(exc_val)
                }
            )
        else:
            self.logger.info(
                f"Request completed",
                extra={
                    "request_id": self.request_id,
                    "duration_ms": round(duration_ms, 1)
                }
            )
        
        return False  # Don't suppress exceptions

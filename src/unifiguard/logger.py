import logging
import uuid
from pathlib import Path


def setup_logger(log_level: str, log_file: Path) -> logging.Logger:
    """Configure and return a logger with file and console handlers.

    Uses a unique logger name per call to avoid handler accumulation
    across multiple invocations in the same process.
    """
    log_file = Path(log_file)
    log_file.parent.mkdir(parents=True, exist_ok=True)

    logger = logging.getLogger(f"unifiguard.{uuid.uuid4().hex[:8]}")
    logger.setLevel(getattr(logging, log_level.upper(), logging.INFO))
    logger.propagate = False

    fmt = logging.Formatter("%(asctime)s [%(levelname)-7s] %(message)s",
                             datefmt="%Y-%m-%d %H:%M:%S")

    file_handler = logging.FileHandler(log_file)
    file_handler.setFormatter(fmt)
    logger.addHandler(file_handler)

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(fmt)
    logger.addHandler(console_handler)

    return logger

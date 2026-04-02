import logging
import os
from pathlib import Path
from unifiguard.logger import setup_logger


def test_logger_returns_logger_instance(tmp_path):
    logger = setup_logger("INFO", tmp_path / "test.log")
    assert isinstance(logger, logging.Logger)


def test_logger_respects_level(tmp_path):
    logger = setup_logger("DEBUG", tmp_path / "test.log")
    assert logger.level == logging.DEBUG


def test_logger_creates_log_file(tmp_path):
    log_path = tmp_path / "logs" / "unifiguard_test.log"
    setup_logger("INFO", log_path)
    assert log_path.exists()


def test_logger_does_not_duplicate_handlers(tmp_path):
    log_path = tmp_path / "test.log"
    setup_logger("INFO", log_path)
    logger = setup_logger("INFO", log_path)
    # Each call should produce a fresh named logger, not stack handlers
    assert len(logger.handlers) == 2  # file + console


def test_logger_warning_level(tmp_path):
    logger = setup_logger("WARNING", tmp_path / "test.log")
    assert logger.level == logging.WARNING

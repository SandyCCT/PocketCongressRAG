import logging
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path
import tempfile
import unittest

from app.logging_config import LOGGER_NAME, configure_logging


class LoggingConfigTests(unittest.TestCase):
    def setUp(self) -> None:
        self.logger = logging.getLogger(LOGGER_NAME)
        self.original_handlers = self.logger.handlers[:]
        self.original_level = self.logger.level
        self.original_propagate = self.logger.propagate
        self.logger.handlers = []

    def tearDown(self) -> None:
        for handler in self.logger.handlers:
            handler.close()
        self.logger.handlers = self.original_handlers
        self.logger.setLevel(self.original_level)
        self.logger.propagate = self.original_propagate

    def test_configures_console_and_daily_file_handlers_once(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            logger = configure_logging(
                log_dir=temp_dir,
                log_level="DEBUG",
                retention_days=7,
                file_logging_enabled=True,
            )
            configure_logging(
                log_dir=temp_dir,
                log_level="DEBUG",
                retention_days=7,
                file_logging_enabled=True,
            )

            self.assertEqual(len(logger.handlers), 2)
            file_handlers = [
                handler
                for handler in logger.handlers
                if isinstance(handler, TimedRotatingFileHandler)
            ]
            self.assertEqual(len(file_handlers), 1)
            self.assertEqual(file_handlers[0].backupCount, 7)
            self.assertEqual(file_handlers[0].suffix, "%Y-%m-%d")
            self.assertEqual(logger.level, logging.DEBUG)
            self.assertFalse(logger.propagate)

            logger.debug("daily file handler test")
            file_handlers[0].flush()
            with open(
                file_handlers[0].baseFilename,
                encoding="utf-8",
            ) as log_file:
                self.assertIn("daily file handler test", log_file.read())

    def test_rejects_invalid_retention_days(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            with self.assertRaisesRegex(ValueError, "必須大於等於 1"):
                configure_logging(
                    log_dir=temp_dir,
                    retention_days=0,
                    file_logging_enabled=True,
                )

    def test_recreates_log_directory_before_writing(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            log_dir = Path(temp_dir) / "logs"
            logger = configure_logging(
                log_dir=log_dir,
                file_logging_enabled=True,
            )
            log_dir.rmdir()

            logger.info("recreate directory test")
            for handler in logger.handlers:
                handler.flush()

            log_file = log_dir / "pocket_congress.log"
            self.assertTrue(log_file.is_file())
            self.assertIn("recreate directory test", log_file.read_text("utf-8"))

    def test_configures_console_only_without_creating_log_directory(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            log_dir = Path(temp_dir) / "logs"
            logger = configure_logging(
                log_dir=log_dir,
                retention_days=0,
                file_logging_enabled=False,
            )

            self.assertEqual(len(logger.handlers), 1)
            self.assertFalse(
                any(
                    isinstance(handler, TimedRotatingFileHandler)
                    for handler in logger.handlers
                )
            )
            self.assertFalse(log_dir.exists())


if __name__ == "__main__":
    unittest.main()

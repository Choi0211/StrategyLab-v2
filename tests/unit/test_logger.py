import logging
import unittest

from strategylab.core import configure_logger


class LoggerTest(unittest.TestCase):
    def test_logger_initializes_with_stream_handler(self) -> None:
        logger = configure_logger(name="strategylab.test", level="DEBUG")

        self.assertEqual(logger.level, logging.DEBUG)
        self.assertEqual(len(logger.handlers), 1)
        self.assertFalse(logger.propagate)


if __name__ == "__main__":
    unittest.main()

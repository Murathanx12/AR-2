"""Colored console logging for Alfred/Sonny."""
import logging
import sys

COLORS = {
    'DEBUG': '\033[36m',    # cyan
    'INFO': '\033[32m',     # green
    'WARNING': '\033[33m',  # yellow
    'ERROR': '\033[31m',    # red
    'CRITICAL': '\033[35m', # magenta
}
RESET = '\033[0m'

class ColorFormatter(logging.Formatter):
    def format(self, record):
        color = COLORS.get(record.levelname, '')
        record.levelname = f"{color}{record.levelname}{RESET}"
        return super().format(record)

def setup_logger(name: str, level=logging.DEBUG) -> logging.Logger:
    logger = logging.getLogger(name)
    if not logger.handlers:
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(ColorFormatter('[%(levelname)s] %(name)s: %(message)s'))
        logger.addHandler(handler)
    logger.setLevel(level)
    return logger

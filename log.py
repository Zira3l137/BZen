import logging

BLACK = "\x1b[30m"
RED = "\x1b[31m"
GREEN = "\x1b[32m"
YELLOW = "\x1b[33m"
BLUE = "\x1b[34m"
MAGENTA = "\x1b[35m"
CYAN = "\x1b[36m"
WHITE = "\x1b[37m"
RESET = "\x1b[0m"

log_level = {0: logging.ERROR, 1: logging.WARNING, 2: logging.INFO, 3: logging.DEBUG}
level_color = {0: RED, 1: YELLOW, 2: GREEN, 3: CYAN}


class ColoredFormatter(logging.Formatter):
    FORMATS = {
        logging.ERROR: f"[{RED}%(levelname)s{RESET} - %(filename)s - %(funcName)s - %(lineno)d] %(message)s",
        logging.WARNING: f"[{YELLOW}%(levelname)s{RESET} - %(filename)s - %(funcName)s - %(lineno)d] %(message)s",
        logging.INFO: f"[{GREEN}%(levelname)s{RESET} - %(filename)s - %(funcName)s - %(lineno)d] %(message)s",
        logging.DEBUG: f"[{CYAN}%(levelname)s{RESET} - %(filename)s - %(funcName)s - %(lineno)d] %(message)s",
    }

    def format(self, record):
        log_fmt = self.FORMATS.get(record.levelno)
        formatter = logging.Formatter(log_fmt)
        return formatter.format(record)


def logging_setup(verbosity: int):
    if verbosity < 0:
        verbosity = abs(verbosity)
    elif verbosity > 3:
        verbosity = 3

    logger = logging.getLogger()
    logger.setLevel(log_level[verbosity])

    ch = logging.StreamHandler()
    ch.setFormatter(ColoredFormatter())
    logger.addHandler(ch)

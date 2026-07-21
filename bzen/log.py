import logging
from pathlib import Path
from typing import Optional

BLACK = "\x1b[30m"
RED = "\x1b[31m"
GREEN = "\x1b[32m"
YELLOW = "\x1b[33m"
BLUE = "\x1b[34m"
MAGENTA = "\x1b[35m"
CYAN = "\x1b[36m"
WHITE = "\x1b[37m"
RESET = "\x1b[0m"

"""
Color escape sequences for the colored log output.

These constants are ANSI escape codes that set terminal text color.
The RESET code (0m) clears all formatting and returns the terminal
to its default color and style.
"""

log_level = {0: logging.ERROR, 1: logging.WARNING, 2: logging.INFO, 3: logging.DEBUG}

"""
Mapping from verbosity level to the corresponding Python logging level.

The verbosity levels are:
- 0: Only errors
- 1: Errors and warnings
- 2: Errors, warnings, and info messages
- 3: All messages including debug

The default verbosity is 0 (errors only).
"""

level_color = {0: RED, 1: YELLOW, 2: GREEN, 3: CYAN}

"""
Mapping from verbosity level to the color escape sequence used to
format log messages at that level.

- Level 0 (ERROR) is formatted with red
- Level 1 (WARNING) is formatted with yellow
- Level 2 (INFO) is formatted with green
- Level 3 (DEBUG) is formatted with cyan
"""


class ColoredFormatter(logging.Formatter):
    """
    A logging formatter that adds ANSI color codes to log messages.

    This formatter adds colored output to the terminal based on the
    logging level. Errors are red, warnings are yellow, info is green,
    and debug is cyan.

    The formatter is configured through the FORMATS class attribute,
    which maps logging levels to format strings. The format strings
    use Python's logging format syntax (%(levelname)s, %(message)s,
    etc.) and include the color escape sequences.
    """
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


def logging_setup(verbosity: int, log_file: Optional[Path | str] = None):
    """
    Configure logging for the BZen project.

    This function sets up the root logger with a colored stream handler
    and an optional file handler for persistent log output.

    The verbosity level controls the minimum level of messages that are
    logged:
    - 0: Only errors
    - 1: Errors and warnings
    - 2: Errors, warnings, and info messages
    - 3: All messages including debug

    If the verbosity level is negative, its absolute value is used.
    If the verbosity level is greater than 3, it is capped at 3.

    Parameters:
        verbosity: Integer verbosity level (default: 0)
        log_file: Path to a log file (optional)
    """
    if verbosity < 0:
        verbosity = abs(verbosity)
    elif verbosity > 3:
        verbosity = 3

    logger = logging.getLogger()
    logger.setLevel(log_level[verbosity])
    logger.handlers.clear()

    ch = logging.StreamHandler()
    ch.setFormatter(ColoredFormatter())
    logger.addHandler(ch)

    if log_file:
        fh = logging.FileHandler(log_file, encoding="utf-8")
        fh.setFormatter(logging.Formatter("[%(levelname)s - %(filename)s - %(funcName)s - %(lineno)d] %(message)s"))
        logger.addHandler(fh)

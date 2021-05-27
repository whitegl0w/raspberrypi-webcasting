import logging


class ColorHandler(logging.StreamHandler):
    COLOR = {
        "DEBUG": "\x1b[34m",     # blue
        "INFO": "\x1b[32m",      # green
        "WARNING": "\x1b[33m",   # yellow
        "ERROR": "\x1b[31m",     # red
        "CRITICAL": "\x1b[31m",  # red
    }

    def __init__(self):
        super().__init__()
        self.setFormatter(logging.Formatter(fmt="%(levelname)s [%(name)s]: %(message)s"))

    def emit(self, record):
        record.levelname = ColorHandler.COLOR[record.levelname] + record.levelname + '\x1b[0m'
        super().emit(record)

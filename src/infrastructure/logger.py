import logging
import sys


class Logger:
    """Structured application logger. One instance per process via the singleton in dependencies.py."""

    def __init__(self, name: str = "depthai", level: int = logging.INFO) -> None:
        self._log = logging.getLogger(name)
        if not self._log.handlers:
            handler = logging.StreamHandler(sys.stdout)
            handler.setFormatter(
                logging.Formatter(
                    fmt="%(asctime)s  %(levelname)-8s  %(message)s",
                    datefmt="%Y-%m-%d %H:%M:%S",
                )
            )
            self._log.addHandler(handler)
            self._log.setLevel(level)
            self._log.propagate = False

    def info(self, msg: str, **ctx) -> None:
        self._log.info(self._fmt(msg, ctx))

    def warning(self, msg: str, **ctx) -> None:
        self._log.warning(self._fmt(msg, ctx))

    def error(self, msg: str, **ctx) -> None:
        self._log.error(self._fmt(msg, ctx))

    def debug(self, msg: str, **ctx) -> None:
        self._log.debug(self._fmt(msg, ctx))

    @staticmethod
    def _fmt(msg: str, ctx: dict) -> str:
        if not ctx:
            return msg
        pairs = "  ".join(f"{k}={v}" for k, v in ctx.items())
        return f"{msg}  |  {pairs}"

from __future__ import annotations

import logging
import sys


def configure_logging(level: str = "INFO") -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)-7s %(name)s | %(message)s", "%H:%M:%S")
    )
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level)

    # asyncpg/sqlalchemy are chatty at INFO.
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    # passlib 1.7.4 probes bcrypt's removed __about__ attribute and logs the
    # traceback it already handles. Hashing works; the noise does not help.
    logging.getLogger("passlib.handlers.bcrypt").setLevel(logging.ERROR)

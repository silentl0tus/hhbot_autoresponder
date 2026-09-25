import logging
import sys
import structlog
from pathlib import Path


def setup_logging():
    log_dir = Path("logs")
    log_dir.mkdir(exist_ok=True)

    # Configure standard python logging
    logging.basicConfig(
        format="%(message)s",
        level=logging.INFO,
        handlers=[logging.FileHandler("logs/log.txt", mode="a", encoding="utf-8"), logging.StreamHandler(sys.stdout)],
    )

    # Configure structlog to route through standard logging
    structlog.configure(
        processors=[
            structlog.stdlib.add_log_level,
            structlog.stdlib.add_logger_name,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            # If we use ConsoleRenderer, it formats nicely with colors, which is ok for file if we strip colors,
            # but usually we use JSONRenderer for files. However, to keep it simple and output same to console and file:
            structlog.dev.ConsoleRenderer(colors=False),
        ],
        wrapper_class=structlog.stdlib.BoundLogger,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )

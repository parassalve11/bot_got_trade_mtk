import json
import logging
from datetime import datetime, timezone
from logging.handlers import RotatingFileHandler


class JsonFormatter(logging.Formatter):
    def format(self, record):
        data = {
            "at": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        for key in ("event_pk", "event_id", "operation", "status", "reason"):
            if hasattr(record, key):
                data[key] = getattr(record, key)
        # Never serialize raw HTTP requests, configuration, MT5 credentials or traceback locals.
        if record.exc_info:
            data["exception_type"] = record.exc_info[0].__name__
        return json.dumps(data, ensure_ascii=True)


def configure_logging(settings, role):
    settings.log_directory.mkdir(parents=True, exist_ok=True)
    formatter = JsonFormatter()
    file_handler = RotatingFileHandler(
        settings.log_directory / f"{role}.jsonl", maxBytes=5_000_000, backupCount=5, encoding="utf-8"
    )
    stream_handler = logging.StreamHandler()
    for handler in (file_handler, stream_handler):
        handler.setFormatter(formatter)
    root = logging.getLogger("app")
    root.setLevel(logging.INFO)
    root.handlers[:] = [file_handler, stream_handler]
    root.propagate = False
    logging.getLogger("uvicorn.access").disabled = True  # URL contains webhook credential.

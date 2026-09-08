"""Логирование с ротацией и вырезанием секретов из сообщений."""

from __future__ import annotations

import logging
import re
from logging.handlers import RotatingFileHandler
from pathlib import Path

_LOG_FORMAT = "%(asctime)s %(levelname)-8s %(name)s: %(message)s"
_REDACTED = "***"

#: Токен бота вида 123456789:AAE...  — вырезается из любого текста.
_TOKEN_RE = re.compile(r"\b\d{6,12}:[A-Za-z0-9_-]{30,}\b")


class SecretRedactingFilter(logging.Filter):
    """Убирает из записей токен бота и явно зарегистрированные секреты (код доступа)."""

    def __init__(self) -> None:
        super().__init__()
        self._secrets: set[str] = set()

    def add_secret(self, secret: str | None) -> None:
        if secret and len(secret) >= 3:
            self._secrets.add(secret)

    def _scrub(self, text: str) -> str:
        for secret in self._secrets:
            text = text.replace(secret, _REDACTED)
        return _TOKEN_RE.sub(_REDACTED, text)

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            message = record.getMessage()
        except Exception:  # pragma: no cover - защитный путь
            return True
        scrubbed = self._scrub(message)
        if scrubbed != message:
            record.msg = scrubbed
            record.args = ()
        return True


#: Единственный экземпляр фильтра — в него регистрируются секреты приложения.
redactor = SecretRedactingFilter()


def setup_logging(level: str = "INFO", log_file: Path | None = None) -> None:
    """Настраивает корневой логгер: консоль + файл с ротацией."""
    root = logging.getLogger()
    root.setLevel(level.upper())
    for handler in list(root.handlers):
        root.removeHandler(handler)

    formatter = logging.Formatter(_LOG_FORMAT)

    console = logging.StreamHandler()
    console.setFormatter(formatter)
    console.addFilter(redactor)
    root.addHandler(console)

    if log_file is not None:
        log_file.parent.mkdir(parents=True, exist_ok=True)
        file_handler = RotatingFileHandler(
            log_file, maxBytes=5 * 1024 * 1024, backupCount=5, encoding="utf-8"
        )
        file_handler.setFormatter(formatter)
        file_handler.addFilter(redactor)
        root.addHandler(file_handler)

    logging.getLogger("aiogram.event").setLevel(logging.WARNING)

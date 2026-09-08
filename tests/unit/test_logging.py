"""Секреты не должны попадать в логи (FR: безопасность, research.md R7)."""

from __future__ import annotations

import logging
from pathlib import Path

from printbot.util.logging import SecretRedactingFilter, redactor, setup_logging

TOKEN = "123456789:AAHdqTcvCH1vGWJxfSeofSAs0K5PALDsaw"
CODE = "SECRET42"


def test_token_is_redacted_by_pattern() -> None:
    log_filter = SecretRedactingFilter()
    record = logging.LogRecord("t", logging.INFO, __file__, 1, f"токен {TOKEN} утёк", None, None)
    log_filter.filter(record)
    assert TOKEN not in record.getMessage()
    assert "***" in record.getMessage()


def test_registered_secret_is_redacted() -> None:
    log_filter = SecretRedactingFilter()
    log_filter.add_secret(CODE)
    record = logging.LogRecord("t", logging.INFO, __file__, 1, f"код {CODE}", None, None)
    log_filter.filter(record)
    assert CODE not in record.getMessage()


def test_short_values_are_not_registered() -> None:
    log_filter = SecretRedactingFilter()
    log_filter.add_secret("ab")
    log_filter.add_secret(None)
    record = logging.LogRecord("t", logging.INFO, __file__, 1, "ab cd", None, None)
    log_filter.filter(record)
    assert record.getMessage() == "ab cd"


def test_secrets_absent_from_log_file(tmp_path: Path) -> None:
    log_file = tmp_path / "printbot.log"
    setup_logging("INFO", log_file)
    redactor.add_secret(CODE)
    try:
        logging.getLogger("printbot.test").info("старт с токеном %s и кодом %s", TOKEN, CODE)
        for handler in logging.getLogger().handlers:
            handler.flush()
        content = log_file.read_text(encoding="utf-8")
        assert TOKEN not in content
        assert CODE not in content
        assert "***" in content
    finally:
        logging.getLogger().handlers.clear()

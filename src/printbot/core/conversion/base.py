"""Протокол конвертации документов (contracts/printer-backend.md)."""

from __future__ import annotations

from pathlib import Path
from typing import Protocol, runtime_checkable

from printbot.core.models import ErrorCode


class ConversionError(RuntimeError):
    """Отказ конвертации с кодом из общей таксономии."""

    def __init__(self, code: ErrorCode, detail: str = "") -> None:
        super().__init__(f"{code}: {detail}" if detail else str(code))
        self.code = code
        self.detail = detail


@runtime_checkable
class DocumentConverter(Protocol):
    async def to_pdf(self, source: Path, out_dir: Path, timeout_s: float) -> Path:
        """Возвращает путь к PDF. Входной PDF возвращается без изменений."""

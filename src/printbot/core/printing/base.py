"""Протокол печати (contracts/printer-backend.md)."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, runtime_checkable

from printbot.core.models import DuplexMode, ErrorCode


class PrintError(RuntimeError):
    """Отказ печати с кодом из общей таксономии."""

    def __init__(self, code: ErrorCode, detail: str = "") -> None:
        super().__init__(f"{code}: {detail}" if detail else str(code))
        self.code = code
        self.detail = detail


@dataclass(frozen=True, slots=True)
class PrintOptions:
    system_name: str
    duplex: DuplexMode
    copies: int
    paper: str = "A4"
    monochrome: bool = True


@dataclass(frozen=True, slots=True)
class PrinterInfo:
    system_name: str
    supports_duplex: bool


@dataclass(frozen=True, slots=True)
class PrinterStatus:
    available: bool
    reason: ErrorCode | None = None
    queued_jobs: int = 0


@runtime_checkable
class PrinterBackend(Protocol):
    async def list_printers(self) -> list[PrinterInfo]:
        """Принтеры, известные системе. Не бросает исключение из-за недоступности."""

    async def get_status(self, system_name: str) -> PrinterStatus:
        """Текущая доступность принтера и причина недоступности."""

    async def print_pdf(self, pdf: Path, options: PrintOptions, timeout_s: float) -> None:
        """Успех = задание принято спулером. Бросает PrintError."""

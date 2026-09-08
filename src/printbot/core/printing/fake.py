"""Фейковый бэкенд печати для тестов и отладки без принтера."""

from __future__ import annotations

import shutil
from dataclasses import dataclass, field
from pathlib import Path

from printbot.core.models import DuplexMode, ErrorCode, PaperSize
from printbot.core.printing.base import (
    PrinterInfo,
    PrintError,
    PrinterStatus,
    PrintOptions,
)


@dataclass(slots=True)
class PrintCall:
    pdf_name: str
    options: PrintOptions


@dataclass
class FakePrinterBackend:
    """Складывает «напечатанное» в каталог и записывает все вызовы."""

    output_dir: Path
    printers: dict[str, bool] = field(default_factory=dict)  # system_name -> supports_duplex
    a3_printers: set[str] = field(default_factory=set)  # кто умеет A3
    fail_with: ErrorCode | None = None
    unavailable: dict[str, ErrorCode] = field(default_factory=dict)
    calls: list[PrintCall] = field(default_factory=list)
    delay_s: float = 0.0

    def __post_init__(self) -> None:
        self.output_dir = Path(self.output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

    async def list_printers(self) -> list[PrinterInfo]:
        return [
            PrinterInfo(
                system_name=name, supports_duplex=dup, supports_a3=name in self.a3_printers
            )
            for name, dup in self.printers.items()
        ]

    async def get_status(self, system_name: str) -> PrinterStatus:
        if system_name not in self.printers:
            return PrinterStatus(available=False, reason=ErrorCode.PRINTER_OFFLINE)
        reason = self.unavailable.get(system_name)
        if reason is not None:
            return PrinterStatus(available=False, reason=reason)
        return PrinterStatus(available=True, queued_jobs=0)

    async def print_pdf(self, pdf: Path, options: PrintOptions, timeout_s: float) -> None:
        if self.delay_s:
            import asyncio

            await asyncio.sleep(self.delay_s)
        supports_duplex = self.printers.get(options.system_name)
        if supports_duplex is None:
            raise PrintError(ErrorCode.PRINTER_OFFLINE, f"нет принтера {options.system_name}")
        if options.duplex is DuplexMode.DUPLEX_LONG and not supports_duplex:
            raise PrintError(ErrorCode.INTERNAL, "дуплекс запрошен у принтера без дуплекса")
        if not options.copies >= 1:
            raise PrintError(ErrorCode.INTERNAL, f"некорректное число копий: {options.copies}")
        if options.paper is PaperSize.A3 and options.system_name not in self.a3_printers:
            raise PrintError(ErrorCode.INTERNAL, "A3 запрошен у принтера без поддержки A3")
        if self.fail_with is not None:
            raise PrintError(self.fail_with, "сценарий теста")

        self.calls.append(PrintCall(pdf_name=pdf.name, options=options))
        shutil.copyfile(pdf, self.output_dir / f"{len(self.calls):03d}-{pdf.name}")

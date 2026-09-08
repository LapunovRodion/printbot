"""Печать и опрос принтеров на Windows (research.md R3, R4)."""

from __future__ import annotations

import asyncio
import logging
import sys
from contextlib import suppress
from pathlib import Path

from printbot.core.models import DuplexMode, ErrorCode
from printbot.core.printing.base import (
    PrinterInfo,
    PrintError,
    PrinterStatus,
    PrintOptions,
)

log = logging.getLogger(__name__)

_DUPLEX_FLAG = {
    DuplexMode.SIMPLEX: "simplex",
    DuplexMode.DUPLEX_LONG: "duplexlong",
}

#: Флаги win32print → коды ошибок (contracts/printer-backend.md).
_STATUS_MAP: tuple[tuple[str, ErrorCode], ...] = (
    ("PRINTER_STATUS_PAPER_JAM", ErrorCode.PAPER_JAM),
    ("PRINTER_STATUS_PAPER_OUT", ErrorCode.PAPER_OUT),
    ("PRINTER_STATUS_PAPER_PROBLEM", ErrorCode.PAPER_OUT),
    ("PRINTER_STATUS_NO_TONER", ErrorCode.NO_TONER),
    ("PRINTER_STATUS_TONER_LOW", ErrorCode.NO_TONER),
    ("PRINTER_STATUS_OFFLINE", ErrorCode.PRINTER_OFFLINE),
    ("PRINTER_STATUS_NOT_AVAILABLE", ErrorCode.PRINTER_OFFLINE),
    ("PRINTER_STATUS_ERROR", ErrorCode.PRINTER_ERROR),
    ("PRINTER_STATUS_PAUSED", ErrorCode.PRINTER_ERROR),
    ("PRINTER_STATUS_DOOR_OPEN", ErrorCode.PRINTER_ERROR),
)


def _win32print():
    """Импорт pywin32 только на Windows — на других платформах возвращает None."""
    if sys.platform != "win32":
        return None
    try:
        import win32print  # type: ignore[import-not-found]
    except ImportError:  # pragma: no cover - только на хосте без pywin32
        log.error("pywin32 не установлен — список принтеров недоступен")
        return None
    return win32print


class WindowsPrinterBackend:
    """Печать через SumatraPDF, статусы и дуплекс — через win32print."""

    def __init__(self, sumatra_path: Path) -> None:
        self.sumatra_path = Path(sumatra_path)

    # --- печать -----------------------------------------------------------------

    def build_command(self, pdf: Path, options: PrintOptions) -> list[str]:
        settings = [_DUPLEX_FLAG[options.duplex], f"{options.copies}x", f"paper={options.paper}"]
        if options.monochrome:
            settings.append("monochrome")
        return [
            str(self.sumatra_path),
            "-print-to",
            options.system_name,
            "-print-settings",
            ",".join(settings),
            "-silent",
            "-exit-when-done",
            str(pdf),
        ]

    async def print_pdf(self, pdf: Path, options: PrintOptions, timeout_s: float) -> None:
        if options.copies < 1:
            raise PrintError(ErrorCode.INTERNAL, f"некорректное число копий: {options.copies}")
        if options.duplex is DuplexMode.DUPLEX_LONG and not await self.supports_duplex(
            options.system_name
        ):
            raise PrintError(ErrorCode.INTERNAL, "дуплекс запрошен у принтера без дуплекса")

        status = await self.get_status(options.system_name)
        if not status.available:
            raise PrintError(status.reason or ErrorCode.PRINTER_ERROR, "принтер недоступен")

        command = self.build_command(pdf, options)
        log.info("Печать: %s", " ".join(command))
        try:
            process = await asyncio.create_subprocess_exec(
                *command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
            )
        except OSError as exc:
            raise PrintError(
                ErrorCode.INTERNAL, f"не удалось запустить {self.sumatra_path}: {exc}"
            ) from exc

        try:
            stdout, _ = await asyncio.wait_for(process.communicate(), timeout=timeout_s)
        except TimeoutError as exc:
            with suppress(ProcessLookupError):
                process.kill()
            with suppress(Exception):
                await asyncio.wait_for(process.wait(), timeout=5)
            raise PrintError(ErrorCode.TIMEOUT, f"печать не уложилась в {timeout_s} с") from exc

        if process.returncode != 0:
            tail = (stdout or b"").decode("utf-8", "replace")[-500:]
            # Принтер мог отвалиться уже во время печати — уточняем причину статусом.
            reason = (await self.get_status(options.system_name)).reason or ErrorCode.PRINTER_ERROR
            raise PrintError(reason, f"SumatraPDF код {process.returncode}: {tail}")

    # --- опрос принтеров --------------------------------------------------------

    async def list_printers(self) -> list[PrinterInfo]:
        return await asyncio.to_thread(self._list_printers_sync)

    def _list_printers_sync(self) -> list[PrinterInfo]:
        win32print = _win32print()
        if win32print is None:
            return []
        flags = win32print.PRINTER_ENUM_LOCAL | win32print.PRINTER_ENUM_CONNECTIONS
        result: list[PrinterInfo] = []
        try:
            for printer in win32print.EnumPrinters(flags, None, 2):
                name = printer["pPrinterName"]
                result.append(
                    PrinterInfo(system_name=name, supports_duplex=self._supports_duplex_sync(name))
                )
        except Exception:  # pragma: no cover - список принтеров не должен ронять бота
            log.exception("Не удалось перечислить принтеры")
        return result

    async def supports_duplex(self, system_name: str) -> bool:
        return await asyncio.to_thread(self._supports_duplex_sync, system_name)

    def _supports_duplex_sync(self, system_name: str) -> bool:
        win32print = _win32print()
        if win32print is None:
            return False
        try:
            return bool(win32print.DeviceCapabilities(system_name, "", 26))  # DC_DUPLEX = 26
        except Exception:  # pragma: no cover - драйвер может не отвечать
            log.warning("Не удалось определить дуплекс у %s", system_name)
            return False

    async def get_status(self, system_name: str) -> PrinterStatus:
        return await asyncio.to_thread(self._get_status_sync, system_name)

    def _get_status_sync(self, system_name: str) -> PrinterStatus:
        win32print = _win32print()
        if win32print is None:
            return PrinterStatus(available=False, reason=ErrorCode.PRINTER_OFFLINE)
        handle = None
        try:
            handle = win32print.OpenPrinter(system_name)
            info = win32print.GetPrinter(handle, 2)
        except Exception as exc:
            log.warning("Принтер %s недоступен: %s", system_name, exc)
            return PrinterStatus(available=False, reason=ErrorCode.PRINTER_OFFLINE)
        finally:
            if handle is not None:
                with suppress(Exception):
                    win32print.ClosePrinter(handle)

        status_bits = int(info.get("Status", 0))
        attributes = int(info.get("Attributes", 0))
        queued = int(info.get("cJobs", 0))

        work_offline = getattr(win32print, "PRINTER_ATTRIBUTE_WORK_OFFLINE", 0x00000400)
        if attributes & work_offline:
            return PrinterStatus(False, ErrorCode.PRINTER_OFFLINE, queued)

        for flag_name, code in _STATUS_MAP:
            flag = getattr(win32print, flag_name, 0)
            if flag and status_bits & flag:
                return PrinterStatus(False, code, queued)

        return PrinterStatus(available=True, reason=None, queued_jobs=queued)

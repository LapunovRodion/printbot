"""Печать и опрос принтеров на Windows (research.md R3, R4)."""

from __future__ import annotations

import asyncio
import logging
import sys
from contextlib import suppress
from pathlib import Path

from printbot.core.models import DuplexMode, ErrorCode, PaperSize
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

#: Формат бумаги в терминах ключа -print-settings у SumatraPDF.
_PAPER_FLAG = {
    PaperSize.A4: "A4",
    PaperSize.A3: "A3",
}

#: Числовые значения из winspool.h. Берём их явно, а не через getattr у модуля:
#: имена констант у pywin32 отличаются между версиями, а биты неизменны.
PRINTER_STATUS_PAUSED = 0x00000001
PRINTER_STATUS_ERROR = 0x00000002
PRINTER_STATUS_PAPER_JAM = 0x00000008
PRINTER_STATUS_PAPER_OUT = 0x00000010
PRINTER_STATUS_PAPER_PROBLEM = 0x00000040
PRINTER_STATUS_OFFLINE = 0x00000080
PRINTER_STATUS_OUTPUT_BIN_FULL = 0x00000800
PRINTER_STATUS_NOT_AVAILABLE = 0x00001000
PRINTER_STATUS_NO_TONER = 0x00040000
PRINTER_STATUS_USER_INTERVENTION = 0x00100000
PRINTER_STATUS_OUT_OF_MEMORY = 0x00200000
PRINTER_STATUS_DOOR_OPEN = 0x00400000
PRINTER_ATTRIBUTE_WORK_OFFLINE = 0x00000400

#: Индексы DeviceCapabilities и поля DEVMODE (wingdi.h).
DC_PAPERS = 2
DC_DUPLEX = 7
DM_DUPLEX = 0x1000

#: Идентификаторы форматов бумаги из wingdi.h.
DMPAPER_A3 = 8
DMPAPER_A4 = 9

#: Биты состояния, при которых печатать нельзя (contracts/printer-backend.md).
#: Порядок важен: первая подошедшая причина показывается пользователю.
#: TONER_LOW, WARMING_UP, POWER_SAVE, BUSY и прочие рабочие состояния сюда НЕ входят —
#: принтер с низким тонером или в спящем режиме печатает нормально.
_STATUS_MAP: tuple[tuple[int, ErrorCode], ...] = (
    (PRINTER_STATUS_PAPER_JAM, ErrorCode.PAPER_JAM),
    (PRINTER_STATUS_PAPER_OUT, ErrorCode.PAPER_OUT),
    (PRINTER_STATUS_PAPER_PROBLEM, ErrorCode.PAPER_OUT),
    (PRINTER_STATUS_NO_TONER, ErrorCode.NO_TONER),
    (PRINTER_STATUS_OFFLINE, ErrorCode.PRINTER_OFFLINE),
    (PRINTER_STATUS_NOT_AVAILABLE, ErrorCode.PRINTER_OFFLINE),
    (PRINTER_STATUS_DOOR_OPEN, ErrorCode.PRINTER_ERROR),
    (PRINTER_STATUS_OUTPUT_BIN_FULL, ErrorCode.PRINTER_ERROR),
    (PRINTER_STATUS_USER_INTERVENTION, ErrorCode.PRINTER_ERROR),
    (PRINTER_STATUS_OUT_OF_MEMORY, ErrorCode.PRINTER_ERROR),
    (PRINTER_STATUS_ERROR, ErrorCode.PRINTER_ERROR),
    (PRINTER_STATUS_PAUSED, ErrorCode.PRINTER_ERROR),
)


def classify_status(status_bits: int, attributes: int) -> ErrorCode | None:
    """Причина недоступности принтера либо None, если печатать можно."""
    if attributes & PRINTER_ATTRIBUTE_WORK_OFFLINE:
        return ErrorCode.PRINTER_OFFLINE
    for flag, code in _STATUS_MAP:
        if status_bits & flag:
            return code
    return None


#: Причина, по которой не удалось получить список принтеров. Нужна для диагностики:
#: без неё пустой список выглядит как «принтеров нет», хотя дело в окружении.
_LAST_ERROR: str | None = None


def last_error() -> str | None:
    """Почему список принтеров пуст, если он пуст не по-настоящему."""
    return _LAST_ERROR


def _win32print():
    """Импорт pywin32 только на Windows — на других платформах возвращает None."""
    global _LAST_ERROR

    if sys.platform != "win32":
        _LAST_ERROR = (
            f"печать доступна только на Windows, текущая система — {sys.platform}"
        )
        return None
    try:
        import win32print  # type: ignore[import-not-found]
    except ImportError as exc:  # pragma: no cover - только на хосте без pywin32
        _LAST_ERROR = (
            f"не удалось загрузить pywin32 ({exc}). "
            "Обычно помогает: .venv\\Scripts\\python -m pywin32_postinstall -install"
        )
        log.error(_LAST_ERROR)
        return None

    _LAST_ERROR = None
    return win32print


class WindowsPrinterBackend:
    """Печать через SumatraPDF, статусы и дуплекс — через win32print."""

    def __init__(self, sumatra_path: Path) -> None:
        self.sumatra_path = Path(sumatra_path)

    # --- печать -----------------------------------------------------------------

    def build_command(self, pdf: Path, options: PrintOptions) -> list[str]:
        settings = [
            _DUPLEX_FLAG[options.duplex],
            f"{options.copies}x",
            f"paper={_PAPER_FLAG[options.paper]}",
        ]
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
        global _LAST_ERROR
        try:
            for printer in win32print.EnumPrinters(flags, None, 2):
                name = printer["pPrinterName"]
                port = printer.get("pPortName", "") or ""
                result.append(
                    PrinterInfo(
                        system_name=name,
                        supports_duplex=self._supports_duplex_sync(name, port),
                        supports_a3=self._supports_a3_sync(name, port),
                    )
                )
        except Exception as exc:  # pragma: no cover - список принтеров не должен ронять бота
            _LAST_ERROR = f"ошибка при опросе очереди печати Windows: {exc}"
            log.exception("Не удалось перечислить принтеры")
            return result

        if not result:
            _LAST_ERROR = (
                "Windows не вернула ни одного принтера: в системе их нет "
                "либо процесс запущен под другой учётной записью"
            )
        return result

    async def supports_duplex(self, system_name: str, port: str = "") -> bool:
        return await asyncio.to_thread(self._supports_duplex_sync, system_name, port)

    def _supports_duplex_sync(self, system_name: str, port: str = "") -> bool:
        """Спрашиваем драйвер, умеет ли принтер печатать с двух сторон.

        Часть драйверов (в частности Pantum PCL6) не отвечает на DeviceCapabilities,
        поэтому есть запасной путь через поля DEVMODE.
        """
        win32print = _win32print()
        if win32print is None:
            return False

        try:
            value = win32print.DeviceCapabilities(system_name, port, DC_DUPLEX)
            if value is not None and value > 0:
                return True
            if value == 0:
                return False  # драйвер ответил явно: дуплекса нет
        except Exception as exc:  # pragma: no cover - драйвер может не отвечать
            log.debug("DeviceCapabilities не ответил для %s: %s", system_name, exc)

        return self._duplex_from_devmode(system_name)

    def _duplex_from_devmode(self, system_name: str) -> bool:
        """Запасной способ: наличие бита DM_DUPLEX в полях DEVMODE принтера."""
        win32print = _win32print()
        if win32print is None:
            return False
        handle = None
        try:
            handle = win32print.OpenPrinter(system_name)
            devmode = win32print.GetPrinter(handle, 2).get("pDevMode")
            if devmode is None:
                log.warning(
                    "Не удалось определить дуплекс у %s: драйвер не отдал DEVMODE", system_name
                )
                return False
            return bool(int(devmode.Fields) & DM_DUPLEX)
        except Exception as exc:  # pragma: no cover - только на хосте
            log.warning("Не удалось определить дуплекс у %s: %s", system_name, exc)
            return False
        finally:
            if handle is not None:
                with suppress(Exception):
                    win32print.ClosePrinter(handle)

    async def supports_a3(self, system_name: str, port: str = "") -> bool:
        return await asyncio.to_thread(self._supports_a3_sync, system_name, port)

    def _supports_a3_sync(self, system_name: str, port: str = "") -> bool:
        """Есть ли A3 среди форматов, которые заявляет драйвер (DC_PAPERS)."""
        win32print = _win32print()
        if win32print is None:
            return False
        try:
            papers = win32print.DeviceCapabilities(system_name, port, DC_PAPERS)
        except Exception as exc:  # pragma: no cover - драйвер может не отвечать
            log.debug("Список форматов недоступен для %s: %s", system_name, exc)
            return False
        if not papers:
            return False
        return DMPAPER_A3 in {int(paper) for paper in papers}

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
        log.debug(
            "Статус %s: Status=0x%08X Attributes=0x%08X cJobs=%s",
            system_name,
            status_bits,
            attributes,
            queued,
        )

        reason = classify_status(status_bits, attributes)
        if reason is not None:
            return PrinterStatus(False, reason, queued)
        return PrinterStatus(available=True, reason=None, queued_jobs=queued)

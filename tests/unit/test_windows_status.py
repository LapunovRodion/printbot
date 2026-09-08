"""Разбор битов состояния принтера Windows (contracts/printer-backend.md).

Логика чистая, поэтому проверяется на любой ОС — реальный win32print не нужен.
"""

from __future__ import annotations

import pytest

from printbot.core.models import ErrorCode
from printbot.core.printing import windows as win

# Рабочие состояния из winspool.h, при которых печать возможна.
PRINTER_STATUS_BUSY = 0x00000200
PRINTER_STATUS_PRINTING = 0x00000400
PRINTER_STATUS_WAITING = 0x00002000
PRINTER_STATUS_PROCESSING = 0x00004000
PRINTER_STATUS_WARMING_UP = 0x00010000
PRINTER_STATUS_TONER_LOW = 0x00020000
PRINTER_STATUS_POWER_SAVE = 0x01000000


def test_idle_printer_is_available() -> None:
    assert win.classify_status(0, 0) is None


@pytest.mark.parametrize(
    "status_bits",
    [
        PRINTER_STATUS_BUSY,
        PRINTER_STATUS_PRINTING,
        PRINTER_STATUS_WAITING,
        PRINTER_STATUS_PROCESSING,
        PRINTER_STATUS_WARMING_UP,
        PRINTER_STATUS_TONER_LOW,
        PRINTER_STATUS_POWER_SAVE,
    ],
)
def test_working_states_do_not_block_printing(status_bits: int) -> None:
    """Занят, греется, спит или мало тонера — печатать всё равно можно."""
    assert win.classify_status(status_bits, 0) is None


@pytest.mark.parametrize(
    ("status_bits", "expected"),
    [
        (win.PRINTER_STATUS_PAPER_JAM, ErrorCode.PAPER_JAM),
        (win.PRINTER_STATUS_PAPER_OUT, ErrorCode.PAPER_OUT),
        (win.PRINTER_STATUS_PAPER_PROBLEM, ErrorCode.PAPER_OUT),
        (win.PRINTER_STATUS_NO_TONER, ErrorCode.NO_TONER),
        (win.PRINTER_STATUS_OFFLINE, ErrorCode.PRINTER_OFFLINE),
        (win.PRINTER_STATUS_NOT_AVAILABLE, ErrorCode.PRINTER_OFFLINE),
        (win.PRINTER_STATUS_DOOR_OPEN, ErrorCode.PRINTER_ERROR),
        (win.PRINTER_STATUS_OUT_OF_MEMORY, ErrorCode.PRINTER_ERROR),
        (win.PRINTER_STATUS_USER_INTERVENTION, ErrorCode.PRINTER_ERROR),
        (win.PRINTER_STATUS_ERROR, ErrorCode.PRINTER_ERROR),
        (win.PRINTER_STATUS_PAUSED, ErrorCode.PRINTER_ERROR),
    ],
)
def test_blocking_states(status_bits: int, expected: ErrorCode) -> None:
    assert win.classify_status(status_bits, 0) is expected


def test_work_offline_attribute_wins() -> None:
    """Галочка «Работать автономно» важнее любых битов состояния."""
    assert (
        win.classify_status(0, win.PRINTER_ATTRIBUTE_WORK_OFFLINE) is ErrorCode.PRINTER_OFFLINE
    )


def test_most_specific_reason_wins() -> None:
    """Замятие вместе с общим флагом ошибки показывается как замятие."""
    bits = win.PRINTER_STATUS_PAPER_JAM | win.PRINTER_STATUS_ERROR
    assert win.classify_status(bits, 0) is ErrorCode.PAPER_JAM


def test_toner_low_together_with_paper_out() -> None:
    bits = PRINTER_STATUS_TONER_LOW | win.PRINTER_STATUS_PAPER_OUT
    assert win.classify_status(bits, 0) is ErrorCode.PAPER_OUT


def test_duplex_constants_match_windows_headers() -> None:
    """DC_DUPLEX=7 из wingdi.h; ошибка в этом числе молча выключает дуплекс."""
    assert win.DC_DUPLEX == 7
    assert win.DM_DUPLEX == 0x1000

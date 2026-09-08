"""Инлайн-клавиатуры и схема callback_data (contracts/bot-interaction.md)."""

from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from printbot.core.models import PrinterView

CB_PRINTER = "pr"
CB_PAPER = "pp"
CB_DUPLEX = "dx"
CB_COPIES = "cp"
CB_CONFIRM = "ok"
CB_LARGE = "big"

DUPLEX_SIMPLEX = "simplex"
DUPLEX_LONG = "duplex"

COPIES_SHORTCUTS = (1, 2, 5)


def _row(*buttons: InlineKeyboardButton) -> list[InlineKeyboardButton]:
    return list(buttons)


def printers_keyboard(views: list[PrinterView]) -> InlineKeyboardMarkup:
    rows = [
        _row(InlineKeyboardButton(text=view.display_name, callback_data=f"{CB_PRINTER}:{view.key}"))
        for view in views
    ]
    rows.append(_row(InlineKeyboardButton(text="Отмена", callback_data=f"{CB_CONFIRM}:cancel")))
    return InlineKeyboardMarkup(inline_keyboard=rows)


def paper_keyboard() -> InlineKeyboardMarkup:
    """Показывается только у принтеров, которые умеют A3."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            _row(
                InlineKeyboardButton(text="A4", callback_data=f"{CB_PAPER}:A4"),
                InlineKeyboardButton(text="A3", callback_data=f"{CB_PAPER}:A3"),
            ),
            _row(InlineKeyboardButton(text="Отмена", callback_data=f"{CB_CONFIRM}:cancel")),
        ]
    )


def duplex_keyboard(supports_duplex: bool) -> InlineKeyboardMarkup:
    buttons = [
        InlineKeyboardButton(text="Односторонняя", callback_data=f"{CB_DUPLEX}:{DUPLEX_SIMPLEX}")
    ]
    if supports_duplex:
        buttons.append(
            InlineKeyboardButton(text="Двусторонняя", callback_data=f"{CB_DUPLEX}:{DUPLEX_LONG}")
        )
    return InlineKeyboardMarkup(
        inline_keyboard=[
            buttons,
            _row(InlineKeyboardButton(text="Отмена", callback_data=f"{CB_CONFIRM}:cancel")),
        ]
    )


def copies_keyboard(max_copies: int) -> InlineKeyboardMarkup:
    shortcuts = [n for n in COPIES_SHORTCUTS if n <= max_copies]
    return InlineKeyboardMarkup(
        inline_keyboard=[
            _row(
                *(
                    InlineKeyboardButton(text=str(n), callback_data=f"{CB_COPIES}:{n}")
                    for n in shortcuts
                )
            ),
            _row(InlineKeyboardButton(text="Отмена", callback_data=f"{CB_CONFIRM}:cancel")),
        ]
    )


def confirm_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            _row(
                InlineKeyboardButton(text="Печатать", callback_data=f"{CB_CONFIRM}:go"),
                InlineKeyboardButton(text="Отмена", callback_data=f"{CB_CONFIRM}:cancel"),
            )
        ]
    )


def large_doc_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            _row(
                InlineKeyboardButton(text="Да, печатать", callback_data=f"{CB_LARGE}:go"),
                InlineKeyboardButton(text="Отмена", callback_data=f"{CB_LARGE}:cancel"),
            )
        ]
    )

"""Состояния диалогов (contracts/bot-interaction.md)."""

from __future__ import annotations

from aiogram.fsm.state import State, StatesGroup


class PrintFlow(StatesGroup):
    choosing_printer = State()
    choosing_paper = State()
    choosing_duplex = State()
    entering_copies = State()
    confirming = State()
    confirming_large = State()


class AuthFlow(StatesGroup):
    waiting_code = State()


class AdminFlow(StatesGroup):
    waiting_new_code = State()

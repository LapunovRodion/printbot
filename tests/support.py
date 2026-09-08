"""Подставные объекты Telegram для прямого вызова хендлеров в тестах."""

from __future__ import annotations

import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.base import StorageKey
from aiogram.fsm.storage.memory import MemoryStorage


@dataclass
class StubUser:
    id: int
    full_name: str = "Тестовый Пользователь"
    username: str | None = "tester"


@dataclass
class StubChat:
    id: int


@dataclass
class StubDocument:
    file_id: str
    file_name: str
    file_size: int
    payload: bytes = b""
    mime_type: str | None = None


@dataclass
class StubMessage:
    """Минимальная поверхность Message, которой пользуются хендлеры."""

    from_user: StubUser
    chat: StubChat
    text: str | None = None
    document: StubDocument | None = None
    photo: Any = None
    answers: list[str] = field(default_factory=list)
    markups: list[Any] = field(default_factory=list)
    deleted: bool = False

    async def answer(self, text: str, reply_markup: Any = None, **kwargs: Any) -> StubMessage:
        self.answers.append(text)
        self.markups.append(reply_markup)
        return self

    async def delete(self) -> None:
        self.deleted = True

    @property
    def last(self) -> str:
        return self.answers[-1] if self.answers else ""


@dataclass
class StubCallback:
    data: str
    message: StubMessage
    from_user: StubUser
    answered: list[str] = field(default_factory=list)

    async def answer(self, text: str = "", show_alert: bool = False, **kwargs: Any) -> None:
        self.answered.append(text)


class StubBot:
    """Подменяет aiogram.Bot: скачивание файла и отправка уведомлений."""

    def __init__(self) -> None:
        self.sent: list[tuple[int, str]] = []

    async def download(self, file: Any, destination: Path, **kwargs: Any) -> None:
        payload = getattr(file, "payload", b"") or b""
        destination = Path(destination)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(payload)

    async def send_message(self, chat_id: int, text: str, **kwargs: Any) -> None:
        self.sent.append((chat_id, text))

    def texts_for(self, chat_id: int) -> list[str]:
        return [text for cid, text in self.sent if cid == chat_id]


def make_state(user_id: int = 1, chat_id: int | None = None) -> FSMContext:
    storage = MemoryStorage()
    key = StorageKey(bot_id=1, chat_id=chat_id if chat_id is not None else user_id, user_id=user_id)
    return FSMContext(storage=storage, key=key)


def make_message(
    user_id: int = 1,
    text: str | None = None,
    document: StubDocument | None = None,
) -> StubMessage:
    return StubMessage(
        from_user=StubUser(id=user_id), chat=StubChat(id=user_id), text=text, document=document
    )


def make_document(payload: bytes, file_name: str = "doc.docx") -> StubDocument:
    return StubDocument(
        file_id=f"file-{file_name}", file_name=file_name, file_size=len(payload), payload=payload
    )


def copy_into(source: Path, target_dir: Path) -> Path:
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / source.name
    shutil.copyfile(source, target)
    return target

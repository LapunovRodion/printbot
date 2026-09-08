"""Доступ по коду от лица пользователя (US3, SC-006)."""

from __future__ import annotations

from printbot.bot.dispatcher import IsAuthorized
from printbot.bot.middlewares.auth import AccessMiddleware
from printbot.bot.routers import auth, printing
from printbot.core.models import Role
from tests.conftest import make_docx_bytes
from tests.support import StubUser, make_document, make_message, make_state


async def _run_middleware(services, user_id: int) -> dict:
    captured: dict = {}

    async def handler(event, data):
        captured.update(data)

    await AccessMiddleware()(
        handler, object(), {"services": services, "event_from_user": StubUser(id=user_id)}
    )
    return captured


async def test_unauthorized_user_is_marked_and_filtered(services) -> None:
    data = await _run_middleware(services, 42)

    assert data["is_authorized"] is False
    assert await IsAuthorized()(object(), is_authorized=data["is_authorized"]) is False


async def test_authorized_user_passes_filter(services) -> None:
    await services.users.get_or_create(42, "Свой")
    await services.users.grant_access(42)

    data = await _run_middleware(services, 42)
    assert data["is_authorized"] is True
    assert await IsAuthorized()(object(), is_authorized=True) is True


async def test_admin_role_assigned_from_config(services) -> None:
    data = await _run_middleware(services, 777)  # ADMIN_IDS=777 в тестовых настройках
    assert data["user"].role is Role.ADMIN


async def test_code_message_is_deleted_from_chat(services, stub_bot) -> None:
    code = await services.access.ensure_code()
    state = make_state(3)
    message = make_message(3, text=code)

    await auth.on_any_message(message, state, services)

    assert message.deleted is True
    assert "Доступ открыт" in message.last
    assert (await services.users.get(3)).is_allowed is True


async def test_wrong_then_right_code(services, stub_bot) -> None:
    code = await services.access.ensure_code()
    state = make_state(4)

    wrong = make_message(4, text="НЕВЕРНО")
    await auth.on_any_message(wrong, state, services)
    assert "Осталось попыток: 4" in wrong.last
    assert (await services.users.get(4)).is_allowed is False

    right = make_message(4, text=code)
    await auth.on_any_message(right, state, services)
    assert (await services.users.get(4)).is_allowed is True


async def test_lockout_message_after_five_attempts(services) -> None:
    await services.access.ensure_code()
    state = make_state(5)
    for _ in range(5):
        message = make_message(5, text="НЕВЕРНО")
        await auth.on_any_message(message, state, services)
    assert "через 15 мин" in message.last


async def test_revoked_user_must_authorize_again(services) -> None:
    code = await services.access.ensure_code()
    await services.users.get_or_create(6, "Уволенный")
    await services.users.grant_access(6)
    await services.access.revoke(6, actor_id=777)

    data = await _run_middleware(services, 6)
    assert data["is_authorized"] is False

    state = make_state(6)
    await auth.on_any_message(make_message(6, text=code), state, services)
    assert (await services.users.get(6)).is_allowed is True


async def test_unauthorized_file_is_not_downloaded(services, stub_bot, fake_printer) -> None:
    """Файл неавторизованного пользователя не скачивается и не печатается (FR-020)."""
    data = await _run_middleware(services, 50)
    assert data["is_authorized"] is False

    state = make_state(50)
    message = make_message(50, document=make_document(make_docx_bytes()))
    # Роутер печати для неавторизованного не вызывается — сообщение идёт в auth.
    await auth.on_any_message(message, state, services)

    assert fake_printer.calls == []
    assert list(services.jobs_root.iterdir()) == []
    assert await services.jobs.list_for_user(50) == []
    assert printing.router is not None

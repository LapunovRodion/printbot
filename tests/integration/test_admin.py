"""Команды администратора и разграничение прав (US5)."""

from __future__ import annotations

import pytest

from printbot.bot.dispatcher import IsAdmin
from printbot.bot.routers import admin, common
from printbot.core.models import AuditEventType, DocumentFormat, DuplexMode, JobStatus
from tests.support import make_message, make_state

ADMIN_ID = 777
USER_ID = 1


@pytest.fixture
async def with_journal(services):
    await services.users.get_or_create(USER_ID, "Иван Иванов", "ivan")
    await services.users.grant_access(USER_ID)
    await services.users.get_or_create(ADMIN_ID, "Админ")
    await services.users.grant_access(ADMIN_ID)
    job = await services.jobs.create(
        user_id=USER_ID,
        chat_id=USER_ID,
        file_name="отчёт.docx",
        source_format=DocumentFormat.DOCX,
        file_size_bytes=2048,
        printer_name=services.printers.system_names[0],
        duplex_mode=DuplexMode.DUPLEX_LONG,
        copies=3,
    )
    await services.jobs.set_status(job.id, JobStatus.CONVERTING)
    await services.jobs.set_status(job.id, JobStatus.PRINTING)
    await services.jobs.set_status(job.id, JobStatus.DONE, page_count=4)
    return services


async def test_journal_shows_job_details(with_journal) -> None:
    message = make_message(ADMIN_ID, text="/journal")
    await admin.cmd_journal(message, with_journal)

    text = message.last
    assert "отчёт.docx" in text
    assert "3 коп." in text
    assert "двусторонняя" in text
    assert "Иван Иванов" in text
    assert "напечатано" in text


async def test_journal_respects_limit(with_journal) -> None:
    for index in range(5):
        await with_journal.jobs.create(
            user_id=USER_ID,
            chat_id=USER_ID,
            file_name=f"doc{index}.pdf",
            source_format=DocumentFormat.PDF,
            file_size_bytes=100,
            printer_name=with_journal.printers.system_names[0],
            duplex_mode=DuplexMode.SIMPLEX,
            copies=1,
        )
    message = make_message(ADMIN_ID, text="/journal 2")
    await admin.cmd_journal(message, with_journal)
    assert message.last.count("№") == 2


@pytest.mark.parametrize(
    "handler_name, text",
    [
        ("cmd_journal", "/journal"),
        ("cmd_users", "/users"),
        ("cmd_revoke", "/revoke 1"),
        ("cmd_purge_journal", "/purge_journal CONFIRM"),
    ],
)
async def test_admin_commands_refused_for_regular_user(with_journal, handler_name, text) -> None:
    message = make_message(USER_ID, text=text)
    await getattr(admin, handler_name)(message, with_journal)
    assert "только администратору" in message.last


async def test_setcode_refused_for_regular_user(with_journal) -> None:
    state = make_state(USER_ID)
    message = make_message(USER_ID, text="/setcode")
    await admin.cmd_setcode(message, state, with_journal)
    assert "только администратору" in message.last
    assert await state.get_state() is None


async def test_admin_filter_uses_role(with_journal) -> None:
    admin_user = await with_journal.users.get(ADMIN_ID)
    regular = await with_journal.users.get(USER_ID)
    from printbot.core.models import Role

    await with_journal.users.set_role(ADMIN_ID, Role.ADMIN)
    admin_user = await with_journal.users.get(ADMIN_ID)

    assert await IsAdmin()(object(), user=admin_user) is True
    assert await IsAdmin()(object(), user=regular) is False


async def test_setcode_changes_code_and_deletes_message(with_journal) -> None:
    await with_journal.access.ensure_code()
    state = make_state(ADMIN_ID)

    await admin.cmd_setcode(make_message(ADMIN_ID, text="/setcode"), state, with_journal)
    code_message = make_message(ADMIN_ID, text="НОВЫЙ-КОД-2026")
    await admin.on_new_code(code_message, state, with_journal)

    assert code_message.deleted is True
    assert "изменён" in code_message.last
    assert await state.get_state() is None

    user = await with_journal.users.get_or_create(99, "Новичок")
    assert (await with_journal.access.submit_code(user, "НОВЫЙ-КОД-2026")).granted is True


async def test_setcode_rejects_short_code(with_journal) -> None:
    state = make_state(ADMIN_ID)
    await admin.cmd_setcode(make_message(ADMIN_ID, text="/setcode"), state, with_journal)
    message = make_message(ADMIN_ID, text="123")
    await admin.on_new_code(message, state, with_journal)

    assert "слишком короткий" in message.last
    assert await state.get_state() is not None


async def test_revoke_and_users(with_journal) -> None:
    listing = make_message(ADMIN_ID, text="/users")
    await admin.cmd_users(listing, with_journal)
    assert "Иван Иванов" in listing.last

    revoke = make_message(ADMIN_ID, text=f"/revoke {USER_ID}")
    await admin.cmd_revoke(revoke, with_journal)
    assert "отозван" in revoke.last

    listing_after = make_message(ADMIN_ID, text="/users")
    await admin.cmd_users(listing_after, with_journal)
    assert "Иван Иванов" not in listing_after.last


async def test_revoke_requires_valid_id(with_journal) -> None:
    message = make_message(ADMIN_ID, text="/revoke не-число")
    await admin.cmd_revoke(message, with_journal)
    assert "Использование" in message.last


async def test_purge_requires_confirmation(with_journal) -> None:
    message = make_message(ADMIN_ID, text="/purge_journal")
    await admin.cmd_purge_journal(message, with_journal)
    assert "CONFIRM" in message.last
    assert await with_journal.jobs.list_recent(10)

    confirmed = make_message(ADMIN_ID, text="/purge_journal CONFIRM")
    await admin.cmd_purge_journal(confirmed, with_journal)
    assert "удалено записей: 1" in confirmed.last
    assert await with_journal.jobs.list_recent(10) == []

    events = {event.event_type for event in await with_journal.jobs.list_events()}
    assert AuditEventType.JOURNAL_PURGED in events


async def test_help_hides_admin_commands_from_users(with_journal) -> None:
    user_help = make_message(USER_ID, text="/help")
    await common.cmd_help(user_help, with_journal)
    assert "/journal" not in user_help.last

    admin_help = make_message(ADMIN_ID, text="/help")
    await common.cmd_help(admin_help, with_journal)
    assert "/journal" in admin_help.last

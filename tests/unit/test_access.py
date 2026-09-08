"""Юнит-тесты кода доступа и защиты от подбора (US3)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from printbot.core.access import generate_code, hash_code, verify_hash
from printbot.core.models import AuditEventType


def test_hash_format_and_verification() -> None:
    stored = hash_code("SECRET123")
    assert stored.startswith("scrypt$")
    assert len(stored.split("$")) == 6
    assert verify_hash("SECRET123", stored)
    assert not verify_hash("secret123", stored)
    assert not verify_hash("другой", stored)


def test_salt_is_random() -> None:
    assert hash_code("SAME") != hash_code("SAME")


def test_broken_hash_does_not_crash() -> None:
    assert verify_hash("any", "мусор") is False


def test_generated_code_avoids_lookalikes() -> None:
    code = generate_code()
    assert len(code) == 8
    assert not set(code) & set("O0I1")


async def test_first_run_generates_code_once(services) -> None:
    code = await services.access.ensure_code()
    assert code and len(code) == 8
    assert await services.access.ensure_code() is None


async def test_correct_code_grants_access(services) -> None:
    code = await services.access.ensure_code()
    user = await services.users.get_or_create(5, "Новичок")

    result = await services.access.submit_code(user, code)

    assert result.granted is True
    assert (await services.users.get(5)).is_allowed is True
    events = {event.event_type for event in await services.jobs.list_events()}
    assert AuditEventType.ACCESS_GRANTED in events


async def test_wrong_code_counts_attempts_and_locks(services) -> None:
    await services.access.ensure_code()
    user = await services.users.get_or_create(6, "Подбиратель")

    for expected_left in (4, 3, 2, 1):
        result = await services.access.submit_code(user, "НЕВЕРНО")
        assert result.granted is False
        assert result.attempts_left == expected_left
        user = await services.users.get(6)

    result = await services.access.submit_code(user, "НЕВЕРНО")
    assert result.locked_minutes == 15

    locked_user = await services.users.get(6)
    assert locked_user.locked_until is not None
    events = {event.event_type for event in await services.jobs.list_events()}
    assert AuditEventType.LOCKOUT_STARTED in events


async def test_locked_user_cannot_use_correct_code(services) -> None:
    code = await services.access.ensure_code()
    user = await services.users.get_or_create(7, "Заблокированный")
    for _ in range(5):
        user = await services.users.get(7)
        await services.access.submit_code(user, "НЕВЕРНО")

    user = await services.users.get(7)
    result = await services.access.submit_code(user, code)

    assert result.granted is False
    assert result.locked_minutes is not None
    assert (await services.users.get(7)).is_allowed is False


async def test_lock_survives_restart(services, db) -> None:
    """Блокировка хранится в БД, а не в памяти процесса."""
    await services.access.ensure_code()
    user = await services.users.get_or_create(8, "Пользователь")
    for _ in range(5):
        user = await services.users.get(8)
        await services.access.submit_code(user, "НЕВЕРНО")

    from printbot.storage.users import UserRepository

    fresh_repo = UserRepository(db)
    restored = await fresh_repo.get(8)
    assert restored.locked_until is not None
    assert restored.locked_until > datetime.now(UTC) + timedelta(minutes=10)


async def test_expired_lock_allows_new_attempt(services) -> None:
    code = await services.access.ensure_code()
    user = await services.users.get_or_create(9, "Пользователь")
    user.locked_until = datetime.now(UTC) - timedelta(minutes=1)

    assert services.access.lock_remaining_minutes(user) is None
    assert (await services.access.submit_code(user, code)).granted is True


async def test_code_change_takes_effect_immediately(services) -> None:
    old = await services.access.ensure_code()
    await services.access.set_code("НОВЫЙКОД", actor_id=777)

    user = await services.users.get_or_create(10, "Новичок")
    assert (await services.access.submit_code(user, old)).granted is False
    user = await services.users.get(10)
    assert (await services.access.submit_code(user, "НОВЫЙКОД")).granted is True

    events = {event.event_type for event in await services.jobs.list_events()}
    assert AuditEventType.CODE_CHANGED in events


async def test_revoke_records_event(services) -> None:
    await services.users.get_or_create(11, "Уволенный")
    await services.users.grant_access(11)

    assert await services.access.revoke(11, actor_id=777) is True
    assert (await services.users.get(11)).is_allowed is False
    events = {event.event_type for event in await services.jobs.list_events()}
    assert AuditEventType.ACCESS_REVOKED in events

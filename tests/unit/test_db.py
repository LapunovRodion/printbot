"""Юнит-тесты схемы БД и репозиториев."""

from __future__ import annotations

from printbot.core.models import AccessStatus, DocumentFormat, DuplexMode, JobStatus, Role
from printbot.storage.db import SCHEMA_VERSION, migrate


async def test_migrations_are_idempotent(db) -> None:
    assert await migrate(db) == SCHEMA_VERSION
    assert await migrate(db) == SCHEMA_VERSION


async def test_tables_created(db) -> None:
    async with db.execute("SELECT name FROM sqlite_master WHERE type = 'table'") as cur:
        names = {row["name"] for row in await cur.fetchall()}
    assert {"users", "settings", "print_jobs", "audit_events"} <= names


async def test_user_created_as_pending(users_repo) -> None:
    user = await users_repo.get_or_create(1, "Иван")
    assert user.access_status is AccessStatus.PENDING
    assert user.role is Role.USER
    assert user.is_allowed is False


async def test_grant_and_revoke(users_repo) -> None:
    await users_repo.get_or_create(1, "Иван")
    await users_repo.grant_access(1)
    assert (await users_repo.get(1)).is_allowed is True

    await users_repo.revoke_access(1)
    assert (await users_repo.get(1)).access_status is AccessStatus.REVOKED


async def test_settings_upsert(settings_repo) -> None:
    await settings_repo.set_access_code_hash("hash-1", updated_by=7)
    await settings_repo.set_access_code_hash("hash-2", updated_by=7)
    assert await settings_repo.get_access_code_hash() == "hash-2"


async def test_job_roundtrip(jobs_repo) -> None:
    job = await jobs_repo.create(
        user_id=1,
        chat_id=1,
        file_name="doc.docx",
        source_format=DocumentFormat.DOCX,
        file_size_bytes=1024,
        printer_name="Pantum P5100",
        duplex_mode=DuplexMode.SIMPLEX,
        copies=2,
    )
    assert job.status is JobStatus.QUEUED
    assert await jobs_repo.queue_length("Pantum P5100") == 1

    await jobs_repo.set_status(job.id, JobStatus.CONVERTING)
    done = await jobs_repo.set_status(
        (await jobs_repo.set_status(job.id, JobStatus.PRINTING)).id, JobStatus.DONE
    )
    assert done.status is JobStatus.DONE
    assert done.started_at is not None and done.finished_at is not None
    assert await jobs_repo.queue_length("Pantum P5100") == 0

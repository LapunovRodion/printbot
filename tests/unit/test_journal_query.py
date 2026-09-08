"""Выборки журнала заданий (US5, SC-011)."""

from __future__ import annotations

from printbot.core.models import DocumentFormat, DuplexMode, ErrorCode, JobStatus


async def _job(jobs_repo, name: str, user_id: int = 1):
    return await jobs_repo.create(
        user_id=user_id,
        chat_id=user_id,
        file_name=name,
        source_format=DocumentFormat.PDF,
        file_size_bytes=10,
        printer_name="Pantum P5100",
        duplex_mode=DuplexMode.SIMPLEX,
        copies=1,
    )


async def test_recent_is_newest_first(jobs_repo) -> None:
    for name in ("a.pdf", "b.pdf", "c.pdf"):
        await _job(jobs_repo, name)
    assert [job.file_name for job in await jobs_repo.list_recent(10)] == ["c.pdf", "b.pdf", "a.pdf"]


async def test_recent_respects_limit(jobs_repo) -> None:
    for index in range(7):
        await _job(jobs_repo, f"{index}.pdf")
    assert len(await jobs_repo.list_recent(3)) == 3


async def test_recent_covers_all_users(jobs_repo) -> None:
    await _job(jobs_repo, "mine.pdf", user_id=1)
    await _job(jobs_repo, "theirs.pdf", user_id=2)

    assert len(await jobs_repo.list_recent(10)) == 2
    assert len(await jobs_repo.list_for_user(1)) == 1


async def test_journal_line_contains_report_fields(jobs_repo) -> None:
    from printbot import texts

    job = await _job(jobs_repo, "отчёт.pdf")
    failed = await jobs_repo.set_status(
        job.id, JobStatus.FAILED, error_code=ErrorCode.PAPER_OUT, error_detail="лоток пуст"
    )
    line = texts.job_line(failed)

    assert "отчёт.pdf" in line
    assert "Pantum P5100" in line
    assert "1 коп." in line
    assert "ошибка" in line
    assert "бумага" in line
    assert "лоток пуст" not in line  # техническая деталь остаётся в журнале, не в тексте


async def test_purge_removes_everything(jobs_repo) -> None:
    await _job(jobs_repo, "a.pdf")
    await _job(jobs_repo, "b.pdf")
    assert await jobs_repo.purge() == 2
    assert await jobs_repo.list_recent(10) == []

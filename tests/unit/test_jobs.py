"""Юнит-тесты переходов статусов задания (data-model.md)."""

from __future__ import annotations

import pytest

from printbot.core.models import (
    FINAL_STATUSES,
    DocumentFormat,
    DuplexMode,
    ErrorCode,
    JobStatus,
    can_transition,
)
from printbot.storage.jobs import InvalidStatusTransition


async def _job(jobs_repo, **kwargs):
    params = dict(
        user_id=1,
        chat_id=1,
        file_name="doc.docx",
        source_format=DocumentFormat.DOCX,
        file_size_bytes=1000,
        printer_name="Pantum P5100",
        duplex_mode=DuplexMode.SIMPLEX,
        copies=1,
    )
    params.update(kwargs)
    return await jobs_repo.create(**params)


def test_allowed_transitions() -> None:
    assert can_transition(JobStatus.QUEUED, JobStatus.CONVERTING)
    assert can_transition(JobStatus.CONVERTING, JobStatus.PRINTING)
    assert can_transition(JobStatus.PRINTING, JobStatus.DONE)
    assert can_transition(JobStatus.QUEUED, JobStatus.FAILED)
    assert can_transition(JobStatus.CONVERTING, JobStatus.FAILED)


def test_forbidden_transitions() -> None:
    assert not can_transition(JobStatus.QUEUED, JobStatus.DONE)
    assert not can_transition(JobStatus.PRINTING, JobStatus.QUEUED)
    assert not can_transition(JobStatus.CANCELLED, JobStatus.QUEUED)


def test_final_statuses_are_terminal() -> None:
    for status in FINAL_STATUSES:
        assert not can_transition(status, JobStatus.QUEUED)
        assert not can_transition(status, JobStatus.DONE)


async def test_repo_rejects_invalid_transition(jobs_repo) -> None:
    job = await _job(jobs_repo)
    with pytest.raises(InvalidStatusTransition):
        await jobs_repo.set_status(job.id, JobStatus.DONE)


async def test_failed_job_keeps_error_code(jobs_repo) -> None:
    job = await _job(jobs_repo)
    failed = await jobs_repo.set_status(
        job.id, JobStatus.FAILED, error_code=ErrorCode.PAPER_OUT, error_detail="нет бумаги"
    )
    assert failed.error_code is ErrorCode.PAPER_OUT
    assert failed.finished_at is not None

    with pytest.raises(InvalidStatusTransition):
        await jobs_repo.set_status(job.id, JobStatus.DONE)


async def test_unfinished_jobs_listed(jobs_repo) -> None:
    queued = await _job(jobs_repo)
    printing = await _job(jobs_repo)
    await jobs_repo.set_status(printing.id, JobStatus.CONVERTING)
    await jobs_repo.set_status(printing.id, JobStatus.PRINTING)
    done = await _job(jobs_repo)
    await jobs_repo.set_status(done.id, JobStatus.CONVERTING)
    await jobs_repo.set_status(done.id, JobStatus.PRINTING)
    await jobs_repo.set_status(done.id, JobStatus.DONE)

    ids = {job.id for job in await jobs_repo.list_unfinished()}
    assert ids == {queued.id, printing.id}

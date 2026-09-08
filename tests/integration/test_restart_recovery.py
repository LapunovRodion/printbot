"""Восстановление после перезапуска (US4, FR-019)."""

from __future__ import annotations

from printbot.core.models import DocumentFormat, DuplexMode, ErrorCode, JobStatus


async def _make_job(services, status: JobStatus | None = None, user_id: int = 1):
    job = await services.jobs.create(
        user_id=user_id,
        chat_id=user_id,
        file_name="doc.docx",
        source_format=DocumentFormat.DOCX,
        file_size_bytes=100,
        printer_name=services.printers.system_names[0],
        duplex_mode=DuplexMode.SIMPLEX,
        copies=1,
    )
    if status is JobStatus.PRINTING:
        await services.jobs.set_status(job.id, JobStatus.CONVERTING)
        await services.jobs.set_status(job.id, JobStatus.PRINTING)
    return job


async def test_unfinished_jobs_marked_interrupted(services, stub_bot) -> None:
    queued = await _make_job(services)
    printing_job = await _make_job(services, JobStatus.PRINTING, user_id=2)

    recovered = await services.job_service.recover_unfinished()

    assert recovered == 2
    for job_id in (queued.id, printing_job.id):
        job = await services.jobs.get(job_id)
        assert job.status is JobStatus.FAILED
        assert job.error_code is ErrorCode.INTERRUPTED
        assert job.finished_at is not None


async def test_authors_are_notified(services, stub_bot) -> None:
    await _make_job(services, user_id=3)
    await services.job_service.recover_unfinished()

    texts_sent = stub_bot.texts_for(3)
    assert texts_sent and "прервано перезапуском" in texts_sent[0]


async def test_finished_jobs_untouched(services, stub_bot) -> None:
    done = await _make_job(services)
    await services.jobs.set_status(done.id, JobStatus.CONVERTING)
    await services.jobs.set_status(done.id, JobStatus.PRINTING)
    await services.jobs.set_status(done.id, JobStatus.DONE)

    assert await services.job_service.recover_unfinished() == 0
    assert (await services.jobs.get(done.id)).status is JobStatus.DONE
    assert stub_bot.sent == []


async def test_nothing_to_recover_is_quiet(services, stub_bot) -> None:
    assert await services.job_service.recover_unfinished() == 0
    assert stub_bot.sent == []

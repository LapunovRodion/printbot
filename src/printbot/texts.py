"""Все русские строки интерфейса в одном месте (contracts/bot-interaction.md)."""

from __future__ import annotations

from printbot.core.models import DuplexMode, ErrorCode, JobStatus, PrintJob

SUPPORTED_FORMATS = "DOCX и PDF"

START_AUTHORIZED = (
    "Привет! Пришлите документ ({formats}) как файл — я отправлю его на печать.\n"
    "Подсказка: /help — как это работает, /cancel — отменить оформление."
)
START_NEED_CODE = (
    "Здравствуйте! Этот бот печатает документы на офисных принтерах.\n"
    "Чтобы получить доступ, отправьте код доступа одним сообщением. "
    "Код можно узнать у администратора."
)
HELP = (
    "Как пользоваться:\n"
    "1. Пришлите файл ({formats}) как документ (не как фото).\n"
    "2. Выберите принтер, режим печати и число копий (от 1 до {max_copies}).\n"
    "3. Подтвердите — и заберите распечатку.\n\n"
    "Ограничение размера файла: {max_mb} МБ.\n"
    "Команды: /printers — список принтеров, /status — мои задания, /cancel — отмена."
)
HELP_ADMIN_EXTRA = (
    "\n\nКоманды администратора: /journal [N], /setcode, /revoke <id>, /users, /purge_journal"
)

ACCESS_ASK_CODE = "Чтобы печатать, отправьте код доступа одним сообщением."
ACCESS_GRANTED = "Доступ открыт. Пришлите документ ({formats}) — и напечатаем."
ACCESS_WRONG_CODE = "Код неверный. Осталось попыток: {attempts_left}."
ACCESS_LOCKED = "Слишком много неверных попыток. Попробуйте снова через {minutes} мин."
ACCESS_REVOKED = "Ваш доступ отозван администратором. Введите действующий код доступа."
ACCESS_DENIED_ADMIN = "Команда доступна только администратору."

FILE_NOT_DOCUMENT = (
    "Пришлите файл именно как документ (скрепка → Файл), а не как фото или сжатое медиа."
)
FILE_UNSUPPORTED = "Формат не поддерживается. Поддерживаются только {formats}."
FILE_TOO_LARGE = "Файл слишком большой: {size_mb:.1f} МБ. Максимум — {max_mb} МБ."
FILE_CORRUPT = "Файл повреждён или пуст — напечатать его не получится."
FILE_ENCRYPTED = "Файл защищён паролем. Снимите защиту и пришлите его снова."
FILE_ACCEPTED = "Принят файл «{file_name}»."

ASK_PRINTER = "Выберите принтер:"
ASK_DUPLEX = "Печать с одной стороны или с двух?"
DUPLEX_UNAVAILABLE = (
    "У этого принтера нет двусторонней печати, поэтому доступна только односторонняя."
)
ASK_COPIES = "Сколько копий? Нажмите кнопку или отправьте число от 1 до {max_copies}."
COPIES_INVALID = "Нужно целое число от 1 до {max_copies}."
NO_PRINTERS = "Сейчас нет доступных принтеров. Сообщите администратору."
PRINTER_UNAVAILABLE = "Принтер «{printer}» недоступен: {reason}. Выберите другой."

CONFIRM_SUMMARY = (
    "Проверьте задание:\n"
    "• Файл: {file_name}\n"
    "• Принтер: {printer}\n"
    "• Печать: {duplex}\n"
    "• Копий: {copies}{pages}\n\n"
    "Печатаем?"
)
CONFIRM_LARGE_DOC = (
    "В документе {pages} стр., копий {copies} — это {total} страниц.\n"
    "Точно печатаем?"
)
CANCELLED = "Задание отменено, файл удалён."
DIALOG_EXPIRED = "Оформление задания истекло по времени — файл удалён. Пришлите документ заново."
DRAFT_REPLACED = "Предыдущее незавершённое задание отменено — оформляем новый файл."
STALE_CALLBACK = "Это задание уже неактуально. Пришлите файл заново."

JOB_QUEUED = "Задание №{job_id} принято.\n{summary}\nВ очереди на принтер: {queue}."
JOB_DONE = "Задание №{job_id} отправлено на принтер «{printer}». Можно забирать."
JOB_FAILED = "Задание №{job_id} не выполнено: {reason}"
JOB_INTERRUPTED = (
    "Задание №{job_id} («{file_name}») прервано перезапуском бота и не было напечатано. "
    "Пришлите файл заново, если печать всё ещё нужна."
)
NO_JOBS = "Заданий пока нет."

ERROR_TEXTS: dict[ErrorCode, str] = {
    ErrorCode.UNSUPPORTED_FORMAT: f"формат файла не поддерживается (нужны {SUPPORTED_FORMATS})",
    ErrorCode.FILE_TOO_LARGE: "файл слишком большой",
    ErrorCode.CORRUPT_FILE: "файл повреждён или пуст",
    ErrorCode.ENCRYPTED_FILE: "файл защищён паролем",
    ErrorCode.CONVERSION_FAILED: "не удалось подготовить документ к печати",
    ErrorCode.PRINTER_OFFLINE: "принтер выключен или недоступен по сети",
    ErrorCode.PAPER_OUT: "в принтере закончилась бумага",
    ErrorCode.PAPER_JAM: "в принтере замялась бумага",
    ErrorCode.NO_TONER: "в принтере закончился тонер",
    ErrorCode.PRINTER_ERROR: "принтер сообщает об ошибке",
    ErrorCode.TIMEOUT: "принтер не ответил вовремя",
    ErrorCode.INTERRUPTED: "работа бота была прервана",
    ErrorCode.INTERNAL: "внутренняя ошибка бота",
}

STATUS_TEXTS: dict[JobStatus, str] = {
    JobStatus.QUEUED: "в очереди",
    JobStatus.CONVERTING: "готовится",
    JobStatus.PRINTING: "печатается",
    JobStatus.DONE: "напечатано",
    JobStatus.FAILED: "ошибка",
    JobStatus.CANCELLED: "отменено",
}

DUPLEX_TEXTS: dict[DuplexMode, str] = {
    DuplexMode.SIMPLEX: "односторонняя",
    DuplexMode.DUPLEX_LONG: "двусторонняя",
}

INTERNAL_ERROR = (
    "Что-то пошло не так. Попробуйте ещё раз, а если повторится — сообщите администратору."
)


def error_text(code: ErrorCode | None) -> str:
    if code is None:
        return ERROR_TEXTS[ErrorCode.INTERNAL]
    return ERROR_TEXTS.get(code, ERROR_TEXTS[ErrorCode.INTERNAL])


def job_summary(job: PrintJob, printer_display: str) -> str:
    pages = f", страниц: {job.page_count}" if job.page_count else ""
    return (
        f"«{job.file_name}» → {printer_display}, "
        f"{DUPLEX_TEXTS[job.duplex_mode]}, копий: {job.copies}{pages}"
    )


def job_line(job: PrintJob) -> str:
    when = job.created_at.astimezone().strftime("%d.%m %H:%M") if job.created_at else "—"
    status = STATUS_TEXTS.get(job.status, job.status)
    tail = f" ({error_text(job.error_code)})" if job.error_code else ""
    return (
        f"№{job.id} · {when} · «{job.file_name}» · {job.printer_name} · "
        f"{DUPLEX_TEXTS[job.duplex_mode]} · {job.copies} коп. · {status}{tail}"
    )


# --- администрирование (US5) ---------------------------------------------------

JOURNAL_HEADER = "Последние задания ({count}):"
JOURNAL_EMPTY = "Журнал пуст."
SETCODE_ASK = (
    "Отправьте новый код доступа одним сообщением (4–64 символа). "
    "Сообщение с кодом я сразу удалю. Отмена — /cancel."
)
SETCODE_TOO_SHORT = "Код слишком короткий — нужно не меньше 4 символов."
SETCODE_DONE = (
    "Код доступа изменён и действует сразу. "
    "Ранее авторизованные пользователи доступ сохранили."
)
REVOKE_USAGE = "Использование: /revoke <telegram_id>"
REVOKE_DONE = "Доступ пользователя {target} отозван."
REVOKE_NOT_FOUND = "Пользователь {target} не найден."
USERS_EMPTY = "Авторизованных пользователей нет."
USERS_HEADER = "Авторизованные пользователи ({count}):"
PURGE_USAGE = "Использование: /purge_journal CONFIRM — удалит все записи журнала безвозвратно."
PURGE_DONE = "Из журнала удалено записей: {count}."

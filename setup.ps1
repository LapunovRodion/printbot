<#
.SYNOPSIS
    Первичная настройка PrintBot на компьютере с Windows.

.DESCRIPTION
    Делает всё, что нужно для запуска: проверяет Python и LibreOffice, скачивает
    SumatraPDF, создаёт виртуальное окружение, спрашивает токен бота и принтеры,
    записывает .env и printers.toml, при желании ставит автозапуск.

    Скрипт можно запускать повторно: он не трогает то, что уже настроено.

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File setup.ps1

.PARAMETER SkipTests
    Не запускать набор тестов после установки.

.PARAMETER Reconfigure
    Переспросить настройки, даже если .env и printers.toml уже есть.

.PARAMETER ShowOutput
    Показывать полный вывод pip и pytest, а не только итог по шагам.

.NOTES
    Ход установки пишется в logs\setup.log — его можно смотреть в другом окне:
        Get-Content logs\setup.log -Wait -Tail 30
    Ввод токена бота в лог не попадает: на это время запись приостанавливается.
#>
[CmdletBinding()]
param(
    [switch]$SkipTests,
    [switch]$Reconfigure,
    [switch]$ShowOutput
)

# Внешние программы пишут в stderr в штатном режиме, поэтому 'Stop' здесь не годится:
# ошибки останавливаем вручную через Stop-Setup.
$ErrorActionPreference = 'Continue'
try { [Console]::OutputEncoding = New-Object System.Text.UTF8Encoding($false) } catch {}
try { [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12 } catch {}

$Root = $PSScriptRoot
$Venv = Join-Path $Root '.venv'
$VenvPython = Join-Path $Venv 'Scripts\python.exe'
$VenvPythonw = Join-Path $Venv 'Scripts\pythonw.exe'
$EnvFile = Join-Path $Root '.env'
$EnvExample = Join-Path $Root '.env.example'
$PrintersFile = Join-Path $Root 'printers.toml'
$SumatraExe = Join-Path $Root 'tools\SumatraPDF.exe'
$SumatraUrl = 'https://www.sumatrapdfreader.org/dl/rel/3.5.2/SumatraPDF-3.5.2-64.zip'

$SetupLog = Join-Path $Root 'logs\setup.log'

$script:Step = 0
$script:Warnings = @()
$script:Transcript = $false

function Start-SetupLog {
    # Пишем ход установки в файл, чтобы после закрытия окна осталась картина целиком.
    try {
        New-Item -ItemType Directory -Path (Split-Path $SetupLog) -Force | Out-Null
        Start-Transcript -Path $SetupLog -Append -ErrorAction Stop | Out-Null
        $script:Transcript = $true
    } catch {
        $script:Transcript = $false
    }
}

function Stop-SetupLog {
    if (-not $script:Transcript) { return }
    try { Stop-Transcript | Out-Null } catch {}
    $script:Transcript = $false
}

function Write-Step([string]$Text) {
    $script:Step++
    Write-Host ''
    Write-Host "[$script:Step] $Text" -ForegroundColor Cyan
}

function Write-Ok([string]$Text)   { Write-Host "    OK  $Text" -ForegroundColor Green }
function Write-Info([string]$Text) { Write-Host "        $Text" -ForegroundColor Gray }

function Write-Warn([string]$Text) {
    Write-Host "    !   $Text" -ForegroundColor Yellow
    $script:Warnings += $Text
}

function Stop-Setup([string]$Text) {
    Write-Host ''
    Write-Host "ОШИБКА: $Text" -ForegroundColor Red
    if ($script:Transcript) {
        Write-Host "Подробности в логе: $SetupLog" -ForegroundColor Yellow
    }
    exit 1  # каталог и лог закроет блок finally в конце скрипта
}

function Confirm-Yes([string]$Question, [bool]$Default = $true) {
    $hint = if ($Default) { '[Д/н]' } else { '[д/Н]' }
    $answer = Read-Host "    $Question $hint"
    if ([string]::IsNullOrWhiteSpace($answer)) { return $Default }
    return $answer -match '^(д|y)'
}

function Write-Utf8NoBom([string]$Path, [string]$Text) {
    # Без BOM: иначе pydantic-settings и tomllib спотыкаются о первый ключ.
    [System.IO.File]::WriteAllText($Path, $Text, (New-Object System.Text.UTF8Encoding($false)))
}

function Get-CommandOutput([string]$Exe, [string[]]$Arguments) {
    # Возвращает вывод внешней программы одной строкой; ошибки запуска гасим.
    try {
        $output = & $Exe @Arguments 2>&1 | Out-String
        return $output.Trim()
    } catch {
        return ''
    }
}

function Get-PythonCommand {
    # Ищем подходящий Python: сначала 'python', затем лаунчер 'py -3'.
    $candidates = @(
        @{ Exe = 'python'; Prefix = @() },
        @{ Exe = 'py';     Prefix = @('-3') }
    )
    foreach ($candidate in $candidates) {
        if (-not (Get-Command $candidate.Exe -ErrorAction SilentlyContinue)) { continue }

        $output = Get-CommandOutput $candidate.Exe ($candidate.Prefix + @('--version'))
        if ($output -notmatch '(\d+)\.(\d+)(?:\.(\d+))?') { continue }

        $patch = if ($Matches[3]) { $Matches[3] } else { '0' }
        return [pscustomobject]@{
            Exe     = $candidate.Exe
            Prefix  = $candidate.Prefix
            Version = [version]("{0}.{1}.{2}" -f $Matches[1], $Matches[2], $patch)
        }
    }
    return $null
}

Push-Location $Root
Start-SetupLog
try {

Write-Host ''
Write-Host '=== Установка PrintBot ===' -ForegroundColor White
Write-Info "Каталог проекта: $Root"
if ($script:Transcript) {
    Write-Info "Лог установки: $SetupLog"
    Write-Info 'Смотреть в другом окне: Get-Content logs\setup.log -Wait -Tail 30'
} else {
    Write-Info 'Записать лог в файл не удалось — вывод только на экране'
}

# --- 1. Python -----------------------------------------------------------------

Write-Step 'Проверяю Python'

$python = Get-PythonCommand
if (-not $python) {
    Stop-Setup @'
Python не найден (или это заглушка из Microsoft Store).
Установите Python 3.11 или новее с https://www.python.org/downloads/,
обязательно отметив галочку "Add python.exe to PATH", и запустите скрипт заново.
Либо выполните: winget install Python.Python.3.12
'@
}

if ($python.Version -lt [version]'3.11') {
    Stop-Setup "Нужен Python 3.11 или новее, найден $($python.Version). Обновите Python и повторите."
}
Write-Ok "Python $($python.Version)"

# --- 2. Виртуальное окружение и зависимости ------------------------------------

Write-Step 'Готовлю виртуальное окружение'

if (-not (Test-Path $VenvPython)) {
    Write-Info 'Создаю .venv ...'
    $venvArgs = $python.Prefix + @('-m', 'venv', $Venv)
    & $python.Exe @venvArgs
    if ($LASTEXITCODE -ne 0 -or -not (Test-Path $VenvPython)) {
        Stop-Setup 'Не удалось создать виртуальное окружение'
    }
}
Write-Ok 'Виртуальное окружение готово'

Write-Info 'Устанавливаю зависимости (может занять пару минут) ...'
$pipQuiet = if ($ShowOutput) { @() } else { @('--quiet') }
& $VenvPython -m pip install @pipQuiet --upgrade pip
& $VenvPython -m pip install @pipQuiet -e ".[dev]"
if ($LASTEXITCODE -ne 0) {
    Write-Info 'Повторите с ключом -ShowOutput, чтобы увидеть полный вывод pip.'
    Stop-Setup 'Не удалось установить зависимости (проверьте интернет)'
}
Write-Ok 'Зависимости установлены'

# --- 3. LibreOffice ------------------------------------------------------------

Write-Step 'Проверяю LibreOffice (конвертация DOCX в PDF)'

$sofficeCandidates = @(
    'C:\Program Files\LibreOffice\program\soffice.exe',
    'C:\Program Files (x86)\LibreOffice\program\soffice.exe'
)
$soffice = $sofficeCandidates | Where-Object { Test-Path $_ } | Select-Object -First 1

if (-not $soffice) {
    Write-Warn 'LibreOffice не найден — без него не печатаются файлы DOCX (PDF печатать можно).'
    Write-Info 'Установка займёт около 350 МБ и несколько минут. Это можно сделать и позже:'
    Write-Info 'поставить LibreOffice вручную и запустить setup.ps1 повторно.'
    if ((Get-Command winget -ErrorAction SilentlyContinue) -and
        (Confirm-Yes 'Скачать и установить LibreOffice через winget прямо сейчас?' $false)) {
        Write-Info 'Идёт загрузка. Если зависла — Ctrl+C, установка бота от этого не пострадает.'
        & winget install --id TheDocumentFoundation.LibreOffice --accept-source-agreements --accept-package-agreements
        $soffice = $sofficeCandidates | Where-Object { Test-Path $_ } | Select-Object -First 1
    }
    if (-not $soffice) {
        Write-Info 'Скачать вручную: https://www.libreoffice.org/download/ — затем запустите setup.ps1 снова.'
    }
}
if ($soffice) { Write-Ok $soffice }

# --- 4. SumatraPDF -------------------------------------------------------------

Write-Step 'Проверяю SumatraPDF (печать PDF с дуплексом и копиями)'

if (Test-Path $SumatraExe) {
    Write-Ok $SumatraExe
} else {
    Write-Info 'SumatraPDF не найден в tools\SumatraPDF.exe'
    if (Confirm-Yes 'Скачать portable-версию с sumatrapdfreader.org?') {
        try {
            $zip = Join-Path $env:TEMP 'sumatrapdf.zip'
            $unpack = Join-Path $env:TEMP 'sumatrapdf'
            Write-Info 'Скачиваю ...'
            Invoke-WebRequest -Uri $SumatraUrl -OutFile $zip -UseBasicParsing -ErrorAction Stop
            if (Test-Path $unpack) { Remove-Item $unpack -Recurse -Force }
            Expand-Archive -Path $zip -DestinationPath $unpack -Force -ErrorAction Stop
            $exe = Get-ChildItem $unpack -Filter '*.exe' -Recurse | Select-Object -First 1
            if (-not $exe) { throw 'в архиве нет .exe' }
            New-Item -ItemType Directory -Path (Split-Path $SumatraExe) -Force | Out-Null
            Copy-Item $exe.FullName $SumatraExe -Force
            Remove-Item $zip, $unpack -Recurse -Force -ErrorAction SilentlyContinue
            Write-Ok $SumatraExe
        } catch {
            Write-Warn "Не удалось скачать SumatraPDF: $($_.Exception.Message)"
            Write-Info 'Скачайте portable-версию вручную: https://www.sumatrapdfreader.org/download-free-pdf-viewer'
            Write-Info "и положите файл как $SumatraExe"
        }
    } else {
        Write-Warn 'Без SumatraPDF печать работать не будет.'
    }
}

# --- 5. Токен бота и администраторы --------------------------------------------

Write-Step 'Настраиваю доступ к Telegram'

if ((Test-Path $EnvFile) -and -not $Reconfigure) {
    Write-Ok '.env уже есть — оставляю как есть (перенастроить: setup.ps1 -Reconfigure)'
} else {
    if (-not (Test-Path $EnvExample)) { Stop-Setup "Не найден файл $EnvExample" }

    Write-Info 'Токен бота: в Telegram напишите @BotFather, команда /newbot'
    Write-Info 'Свой числовой ID: напишите @userinfobot'
    Write-Host ''

    # Токен не должен осесть в logs\setup.log — на время ввода запись выключаем.
    Stop-SetupLog

    $token = ''
    while ($token -notmatch '^\d{6,12}:[A-Za-z0-9_-]{30,}$') {
        $token = (Read-Host '    Токен бота').Trim()
        if ($token -notmatch '^\d{6,12}:[A-Za-z0-9_-]{30,}$') {
            Write-Host '    Не похоже на токен (нужен вид 123456789:AAH...). Попробуйте ещё раз.' -ForegroundColor Yellow
        }
    }

    $admins = ''
    while ($admins -notmatch '^\d+(\s*,\s*\d+)*$') {
        $admins = (Read-Host '    Telegram ID администраторов (через запятую)').Trim()
        if ($admins -notmatch '^\d+(\s*,\s*\d+)*$') {
            Write-Host '    Нужны только числа через запятую.' -ForegroundColor Yellow
        }
    }
    $admins = $admins -replace '\s', ''

    $envText = Get-Content $EnvExample -Raw -Encoding UTF8
    $envText = [regex]::Replace($envText, '(?m)^BOT_TOKEN=.*$', "BOT_TOKEN=$token")
    $envText = [regex]::Replace($envText, '(?m)^ADMIN_IDS=.*$', "ADMIN_IDS=$admins")
    if ($soffice) {
        $envText = [regex]::Replace($envText, '(?m)^SOFFICE_PATH=.*$', "SOFFICE_PATH=$soffice")
    }
    Write-Utf8NoBom $EnvFile $envText
    Start-SetupLog
    Write-Ok 'Файл .env записан'
}

# --- 6. Принтеры ---------------------------------------------------------------

Write-Step 'Настраиваю принтеры'

if ((Test-Path $PrintersFile) -and -not $Reconfigure) {
    Write-Ok 'printers.toml уже есть — оставляю как есть (перенастроить: setup.ps1 -Reconfigure)'
} else {
    Write-Info 'Опрашиваю систему ...'
    $raw = Get-CommandOutput $VenvPython @((Join-Path $Root 'tools\list_printers.py'), '--json')

    $printers = @()
    if ($raw -and $raw.StartsWith('[')) {
        try { $printers = @($raw | ConvertFrom-Json) } catch { $printers = @() }
    }

    if ($printers.Count -eq 0) {
        Write-Warn 'Принтеры не найдены. Подключите их под этой учётной записью и запустите: setup.ps1 -Reconfigure'
    } else {
        Write-Host ''
        for ($i = 0; $i -lt $printers.Count; $i++) {
            $p = $printers[$i]
            $duplex = if ($p.supports_duplex) { 'дуплекс есть' } else { 'дуплекса нет' }
            $state = if ($p.available) { 'доступен' } else { "недоступен ($($p.reason))" }
            Write-Host ("    {0}) {1}  —  {2}, {3}" -f ($i + 1), $p.system_name, $duplex, $state)
        }
        Write-Host ''
        $choice = (Read-Host '    Номера принтеров для бота через запятую (Enter — все)').Trim()

        $selected = @()
        if ([string]::IsNullOrWhiteSpace($choice)) {
            $selected = $printers
        } else {
            foreach ($part in ($choice -split ',')) {
                $number = 0
                if ([int]::TryParse($part.Trim(), [ref]$number) -and
                    $number -ge 1 -and $number -le $printers.Count) {
                    $selected += $printers[$number - 1]
                } else {
                    Write-Warn "Номер «$($part.Trim())» пропущен — такого пункта нет"
                }
            }
        }

        if ($selected.Count -eq 0) {
            Write-Warn 'Ничего не выбрано — printers.toml не создан'
        } else {
            $lines = @(
                '# Создано setup.ps1. system_name менять нельзя: он должен совпадать с именем в Windows.',
                ''
            )
            $n = 0
            foreach ($p in $selected) {
                $n++
                $display = (Read-Host "    Как назвать «$($p.system_name)» для сотрудников? (Enter — так же)").Trim()
                if ([string]::IsNullOrWhiteSpace($display)) { $display = $p.system_name }
                $display = $display -replace '"', "'"
                $lines += '[[printer]]'
                $lines += "key = `"p$n`""
                $lines += "display_name = `"$display`""
                $lines += "system_name = `"$($p.system_name)`""
                $lines += "model = `"$($p.system_name)`""
                $lines += 'enabled = true'
                $lines += ''
            }
            Write-Utf8NoBom $PrintersFile ($lines -join "`r`n")
            Write-Ok "Файл printers.toml записан, принтеров: $n"
        }
    }
}

# --- 7. Тесты ------------------------------------------------------------------

if (-not $SkipTests) {
    Write-Step 'Проверяю сборку тестами (принтер не нужен)'
    $pytestArgs = if ($ShowOutput) { @('-v') } else { @('-q') }
    & $VenvPython -m pytest @pytestArgs
    if ($LASTEXITCODE -ne 0) {
        Write-Warn "Тесты не прошли — подробности в $SetupLog, настройку можно продолжать"
    } else {
        Write-Ok 'Все тесты прошли'
    }
}

# --- 8. Автозапуск -------------------------------------------------------------

Write-Step 'Автозапуск при входе в систему'

if (-not (Get-Command Register-ScheduledTask -ErrorAction SilentlyContinue)) {
    Write-Warn 'Планировщик заданий недоступен из PowerShell — настройте автозапуск по README.md'
} else {
    $taskExists = $null -ne (Get-ScheduledTask -TaskName 'PrintBot' -ErrorAction SilentlyContinue)
    if ($taskExists) {
        Write-Ok 'Задача PrintBot в планировщике уже есть'
    } elseif (Confirm-Yes 'Настроить автозапуск бота при входе в систему?') {
        try {
            $action = New-ScheduledTaskAction -Execute $VenvPythonw -Argument '-m printbot' -WorkingDirectory $Root
            $trigger = New-ScheduledTaskTrigger -AtLogOn -User "$env:USERDOMAIN\$env:USERNAME"
            $settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
                -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1) -ExecutionTimeLimit ([TimeSpan]::Zero)
            Register-ScheduledTask -TaskName 'PrintBot' -Action $action -Trigger $trigger -Settings $settings `
                -Description 'Telegram-бот печати документов' -Force -ErrorAction Stop | Out-Null
            Write-Ok 'Задача PrintBot создана (запуск при входе, перезапуск при сбое)'
            Write-Info 'Важно: бот работает в вашей сессии — под LOCAL SYSTEM сетевые принтеры не видны.'
        } catch {
            Write-Warn "Не удалось создать задачу: $($_.Exception.Message)"
            Write-Info 'Создайте её вручную командой из README.md (раздел «Автозапуск»).'
        }
    }
}

# --- Итог ----------------------------------------------------------------------

Write-Host ''
Write-Host '=== Готово ===' -ForegroundColor White

if ($script:Warnings.Count -gt 0) {
    Write-Host ''
    Write-Host 'Осталось доделать:' -ForegroundColor Yellow
    foreach ($w in $script:Warnings) { Write-Host "  - $w" -ForegroundColor Yellow }
}

Write-Host ''
Write-Host 'Запустить бота:' -ForegroundColor White
Write-Host '    .venv\Scripts\python -m printbot' -ForegroundColor Green
Write-Host ''
Write-Info 'При первом запуске в консоли один раз появится КОД ДОСТУПА — запишите его.'
Write-Info 'Дальше код меняется командой /setcode в самом боте.'
Write-Info 'Проверьте двустороннюю печать на каждом принтере (quickstart.md, сценарий 6.2).'
Write-Host ''
Write-Host 'Логи:' -ForegroundColor White
Write-Info "установка — $SetupLog"
Write-Info 'работа бота — logs\printbot.log (смотреть: Get-Content logs\printbot.log -Wait -Tail 30)'
Write-Host ''

} finally {
    Stop-SetupLog
    Pop-Location -ErrorAction SilentlyContinue
}

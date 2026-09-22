param(
    [string]$EnvFile = ".env"
)

$ErrorActionPreference = "Stop"

if (-not (Test-Path $EnvFile)) {
    throw "Файл '$EnvFile' не найден. Запустите скрипт из корня проекта или передайте путь: .\set-weeek-token.ps1 -EnvFile 'D:\path\.env'"
}

$line = Get-Content $EnvFile |
    Where-Object { $_ -match '^\s*WEEEK_API_TOKEN\s*=' } |
    Select-Object -First 1

if (-not $line) {
    throw "В '$EnvFile' не найден WEEEK_API_TOKEN."
}

$token = ($line -replace '^\s*WEEEK_API_TOKEN\s*=\s*', '').Trim()

if (
    ($token.StartsWith('"') -and $token.EndsWith('"')) -or
    ($token.StartsWith("'") -and $token.EndsWith("'"))
) {
    $token = $token.Substring(1, $token.Length - 2)
}

if ([string]::IsNullOrWhiteSpace($token)) {
    throw "WEEEK_API_TOKEN в '$EnvFile' пустой."
}

# Постоянно для текущего пользователя Windows.
[Environment]::SetEnvironmentVariable(
    "WEEEK_API_TOKEN",
    $token,
    [EnvironmentVariableTarget]::User
)

# И сразу для текущего PowerShell.
$env:WEEEK_API_TOKEN = $token

Write-Host ""
Write-Host "OK: WEEEK_API_TOKEN прочитан из $EnvFile и сохранён в пользовательском окружении Windows." -ForegroundColor Green
Write-Host "Полностью перезапустите Codex, чтобы он увидел переменную."
Write-Host ""
Write-Host "Проверка в новом PowerShell:"
Write-Host '  if ($env:WEEEK_API_TOKEN) { "OK: token is set" } else { "NOT SET" }'

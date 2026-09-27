$ErrorActionPreference = 'Stop'
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$envFile = Join-Path $projectRoot '.env.docker'

if (-not (Test-Path $envFile)) {
    throw 'Сначала создайте .env.docker из .env.docker.example.'
}

Write-Warning 'Будут удалены все данные занятий, результаты и PostgreSQL volume.'
$confirmation = Read-Host 'Для полного сброса введите RESET'
if ($confirmation -cne 'RESET') {
    throw 'Сброс отменён.'
}

Push-Location $projectRoot
try {
    docker compose --env-file .env.docker down -v
    if ($LASTEXITCODE -ne 0) { throw 'Не удалось остановить стенд и удалить volume.' }
    docker compose --env-file .env.docker up -d --build
    if ($LASTEXITCODE -ne 0) { throw 'Не удалось поднять стенд.' }
    docker compose --env-file .env.docker run --rm backend python -m app.scripts.bootstrap_demo
    if ($LASTEXITCODE -ne 0) { throw 'Не удалось выполнить bootstrap_demo.' }
    Write-Output 'Демонстрационный стенд создан заново.'
}
finally {
    Pop-Location
}

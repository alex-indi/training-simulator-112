$ErrorActionPreference = 'Stop'
$projectRoot = $PSScriptRoot
$envFile = Join-Path $projectRoot '.env.docker'

function Test-DockerReady {
    $ErrorActionPreference = 'Continue'
    docker info *> $null
    return $LASTEXITCODE -eq 0
}

Push-Location $projectRoot
try {
    if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
        throw 'Установите Docker Desktop и запустите файл снова.'
    }
    docker compose version | Out-Null
    if ($LASTEXITCODE -ne 0) { throw 'Docker Compose недоступен.' }

    $isWindowsHost = [System.Environment]::OSVersion.Platform -eq [System.PlatformID]::Win32NT
    if (-not (Test-DockerReady) -and $isWindowsHost) {
        $desktop = Join-Path $env:ProgramFiles 'Docker\Docker\Docker Desktop.exe'
        if (Test-Path $desktop) {
            Write-Output 'Запускаю Docker Desktop...'
            Start-Process $desktop
            for ($attempt = 0; $attempt -lt 60; $attempt++) {
                Start-Sleep -Seconds 2
                if (Test-DockerReady) { break }
            }
        }
    }
    if (-not (Test-DockerReady)) { throw 'Docker daemon недоступен. Запустите Docker Desktop.' }

    if (-not (Test-Path $envFile)) {
        $template = [System.IO.File]::ReadAllText((Join-Path $projectRoot '.env.docker.example'))
        if ($template -notmatch '(?m)^POSTGRES_PASSWORD=') {
            throw 'В .env.docker.example отсутствует POSTGRES_PASSWORD.'
        }
        $bytes = New-Object byte[] 24
        $random = [System.Security.Cryptography.RandomNumberGenerator]::Create()
        try { $random.GetBytes($bytes) } finally { $random.Dispose() }
        $password = [System.BitConverter]::ToString($bytes).Replace('-', '').ToLowerInvariant()
        $content = [regex]::Replace(
            $template, '(?m)^POSTGRES_PASSWORD=.*$', "POSTGRES_PASSWORD=$password"
        )
        $tempFile = "$envFile.tmp.$PID"
        try {
            $utf8 = [System.Text.UTF8Encoding]::new($false)
            [System.IO.File]::WriteAllText($tempFile, $content, $utf8)
            Move-Item -LiteralPath $tempFile -Destination $envFile
        }
        finally {
            if (Test-Path $tempFile) { Remove-Item -LiteralPath $tempFile }
        }
        Write-Output 'Создан .env.docker с автоматически сгенерированным паролем базы.'
    }

    docker compose --env-file .env.docker up -d --build --wait --wait-timeout 300
    if ($LASTEXITCODE -ne 0) { throw 'Не удалось поднять контейнеры.' }

    $settings = [System.IO.File]::ReadAllText($envFile)
    $postgresUser = [regex]::Match($settings, '(?m)^POSTGRES_USER=(.*)$').Groups[1].Value.Trim()
    $postgresDb = [regex]::Match($settings, '(?m)^POSTGRES_DB=(.*)$').Groups[1].Value.Trim()
    if (-not $postgresUser) { $postgresUser = 'training112' }
    if (-not $postgresDb) { $postgresDb = 'training_simulator_112' }
    $sql = "SELECT EXISTS (SELECT 1 FROM users WHERE username = 'admin') AND EXISTS (SELECT 1 FROM scenario_templates) AND EXISTS (SELECT 1 FROM city_objects) AND EXISTS (SELECT 1 FROM dispatch_services);"
    $demoReady = $sql | docker compose --env-file .env.docker exec -T postgres psql -U $postgresUser -d $postgresDb -At
    if ($LASTEXITCODE -ne 0) { throw 'Не удалось проверить демонстрационные данные.' }
    if (($demoReady -join '').Trim() -ne 't') {
        Write-Output 'Наполняю чистую базу демонстрационными данными...'
        docker compose --env-file .env.docker run --rm backend python -m app.scripts.bootstrap_demo
        if ($LASTEXITCODE -ne 0) { throw 'Не удалось выполнить bootstrap_demo.' }
    }
    else {
        Write-Output 'Демонстрационные данные уже есть; повторное наполнение не требуется.'
    }

    $appPort = [regex]::Match($settings, '(?m)^APP_PORT=(\d+)').Groups[1].Value
    if (-not $appPort) { $appPort = '8080' }
    $appUrl = "http://localhost:$appPort"
    Write-Output "Стенд готов: $appUrl"
    if (-not $env:CI) { Start-Process $appUrl }
}
catch {
    [Console]::Error.WriteLine($_.Exception.Message)
    exit 1
}
finally {
    Pop-Location
}

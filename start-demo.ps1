$ErrorActionPreference = 'Stop'
$projectRoot = $PSScriptRoot
$envFile = Join-Path $projectRoot '.env.docker'

function Test-DockerReady {
    if (-not (Get-Command docker -ErrorAction SilentlyContinue)) { return $false }
    docker compose version *> $null
    if ($LASTEXITCODE -ne 0) { return $false }
    docker info *> $null
    return $LASTEXITCODE -eq 0
}

Push-Location $projectRoot
try {
    $isWindowsHost = [System.Environment]::OSVersion.Platform -eq [System.PlatformID]::Win32NT
    if (-not (Test-DockerReady) -and $isWindowsHost) {
        $desktopCandidates = @(
            (Join-Path $env:LOCALAPPDATA 'Programs\DockerDesktop\Docker Desktop.exe'),
            (Join-Path $env:ProgramFiles 'Docker\Docker\Docker Desktop.exe')
        )
        $desktop = $desktopCandidates | Where-Object { Test-Path $_ } | Select-Object -First 1
        if (-not $desktop) {
            $answer = Read-Host 'Docker Engine и Compose не найдены. Установить Docker Desktop с docker.com? [д/Н]'
            if ($answer -notmatch '^(д|да|y|yes)$') {
                throw 'Установка отменена. Файлы и данные стенда не изменены.'
            }
            $architecture = if ($env:PROCESSOR_ARCHITECTURE -eq 'ARM64') { 'arm64' } else { 'amd64' }
            $installerUrl = "https://desktop.docker.com/win/main/$architecture/Docker%20Desktop%20Installer.exe"
            $installerDir = Join-Path ([System.IO.Path]::GetTempPath()) ("ut112-docker-" + [guid]::NewGuid().ToString('N'))
            New-Item -ItemType Directory -Path $installerDir | Out-Null
            try {
                $installer = Join-Path $installerDir 'Docker Desktop Installer.exe'
                Write-Output 'Скачиваю официальный установщик Docker Desktop...'
                Invoke-WebRequest -Uri $installerUrl -UseBasicParsing -OutFile $installer
                $signature = Get-AuthenticodeSignature -FilePath $installer
                if ($signature.Status -ne 'Valid' -or $signature.SignerCertificate.Subject -notmatch 'Docker') {
                    throw 'Не удалось проверить подпись установщика Docker Desktop.'
                }
                $process = Start-Process -FilePath $installer -ArgumentList @('install', '--user') -Wait -PassThru
                if ($process.ExitCode -ne 0) { throw "Установщик Docker Desktop завершился с кодом $($process.ExitCode)." }
            }
            finally {
                Remove-Item -LiteralPath $installerDir -Recurse -Force -ErrorAction SilentlyContinue
            }
            $desktop = $desktopCandidates | Where-Object { Test-Path $_ } | Select-Object -First 1
            if (-not $desktop) { throw 'Docker Desktop не найден после установки. Завершите его настройку и повторите запуск.' }
        }
        $dockerBin = Join-Path (Split-Path $desktop -Parent) 'resources\bin'
        if (Test-Path $dockerBin) { $env:PATH = "$dockerBin;$env:PATH" }
        if (-not (Test-DockerReady)) {
            Write-Output 'Запускаю Docker Desktop. Завершите первоначальную настройку в его окне.'
            Start-Process $desktop
            for ($attempt = 0; $attempt -lt 180; $attempt++) {
                Start-Sleep -Seconds 2
                if (Test-DockerReady) { break }
            }
        }
    }
    if (-not (Test-DockerReady)) { throw 'Docker Engine и Compose недоступны. Проверьте настройку Docker и повторите запуск.' }

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

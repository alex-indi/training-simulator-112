"""Build a self-contained, offline ZIP with a relocatable CPython and PostgreSQL."""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import platform
import shutil
import stat
import subprocess
import sys
import tarfile
import urllib.request
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DIST = ROOT / "dist"
PYTHON_TAG = "20260924"
PYTHON_VERSION = "3.12.14"
POSTGRES_VERSION = "16.14.0"
PYTHON_BASE = (
    f"https://github.com/astral-sh/python-build-standalone/releases/download/{PYTHON_TAG}"
)
POSTGRES_BASE = "https://repo.maven.apache.org/maven2/io/zonky/test/postgres"

PLATFORMS = {
    "windows-x64": {
        "python_target": "x86_64-pc-windows-msvc",
        "python_sha256": "c5bf8edfe858c1df9891be498b5bbc8761d383df5b9790658b088fea4870433a",
        "postgres_target": "windows-amd64",
        "postgres_sha256": "ce225f9a5216efabaf63cb9e0f4e68eac25f2d071113263a48a193ae5f1f5925",
    },
    "macos-x64": {
        "python_target": "x86_64-apple-darwin",
        "python_sha256": "7ea9761b9069c10b9a20531d568645849d604c59e9c7f11f6659f1e1790c968e",
        "postgres_target": "darwin-amd64",
        "postgres_sha256": "9d082281befccc05f6c25dc0dd196382871543422f3ce850fb46cb035d38616a",
    },
    "macos-arm64": {
        "python_target": "aarch64-apple-darwin",
        "python_sha256": "c2edb321cd32ec2b170df208db0446dccc4398db602ca27cf2079098fb1f7d9d",
        "postgres_target": "darwin-arm64v8",
        "postgres_sha256": "d5d84a7e5103ade5557898fcf51affae69778be559bf9ba44819714c0d68e541",
    },
}


def _assert_native(target: str) -> None:
    machine = platform.machine().lower()
    if target == "windows-x64" and sys.platform == "win32" and machine in {"amd64", "x86_64"}:
        return
    if target == "macos-x64" and sys.platform == "darwin" and machine == "x86_64":
        return
    if target == "macos-arm64" and sys.platform == "darwin" and machine in {"arm64", "aarch64"}:
        return
    raise SystemExit(f"Сборка {target} требует соответствующую платформу, сейчас {sys.platform}/{machine}.")


def _download(url: str, expected_sha256: str, destination: Path) -> Path:
    if destination.exists() and hashlib.sha256(destination.read_bytes()).hexdigest() == expected_sha256:
        return destination
    destination.parent.mkdir(parents=True, exist_ok=True)
    print(f"Downloading {url}", flush=True)
    request = urllib.request.Request(url, headers={"User-Agent": "UT112-portable-builder"})
    with urllib.request.urlopen(request, timeout=120) as response, destination.open("wb") as output:
        shutil.copyfileobj(response, output)
    actual = hashlib.sha256(destination.read_bytes()).hexdigest()
    if actual != expected_sha256:
        destination.unlink(missing_ok=True)
        raise RuntimeError(f"SHA256 mismatch for {url}: {actual}")
    return destination


def _safe_tar_extract(archive: tarfile.TarFile, destination: Path) -> None:
    base = destination.resolve()
    for member in archive.getmembers():
        target = (base / member.name).resolve()
        if target != base and base not in target.parents:
            raise RuntimeError(f"Archive path escapes destination: {member.name}")
    archive.extractall(destination, filter="data")


def _run(*command: str, cwd: Path = ROOT) -> None:
    print("Running", " ".join(command), flush=True)
    subprocess.run(command, cwd=cwd, check=True)


def _copy_source(stage: Path) -> None:
    backend = stage / "backend"
    backend.mkdir()
    for directory in ("app", "migrations", "seed", "scripts"):
        shutil.copytree(
            ROOT / "backend" / directory,
            backend / directory,
            ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
        )
    for filename in ("alembic.ini", "portable_start.py"):
        shutil.copy2(ROOT / "backend" / filename, backend / filename)
    shutil.copytree(ROOT / "frontend" / "dist", stage / "frontend")
    version = subprocess.check_output(
        ["git", "-C", str(ROOT), "rev-parse", "--short=12", "HEAD"], text=True
    ).strip()
    (stage / "VERSION").write_text(version + "\n", encoding="utf-8")


def _install_requirements(stage: Path, cache: Path, target: str) -> None:
    requirements = cache / "requirements-portable.txt"
    _run(
        "uv", "export", "--quiet", "--frozen", "--no-dev", "--no-emit-project",
        "--output-file", str(requirements), cwd=ROOT / "backend",
    )
    python = stage / "python" / ("python.exe" if target == "windows-x64" else "bin/python3")
    if not python.is_file():
        raise RuntimeError(f"Portable Python is missing: {python}")
    _run("uv", "pip", "install", "--python", str(python), "--system", "--require-hashes", "-r", str(requirements))
    _run(str(python), "-E", "-s", "-c", "import asyncpg, alembic, fastapi, socketio, uvicorn")


def _write_launchers(stage: Path, target: str) -> None:
    if target == "windows-x64":
        (stage / "Start.cmd").write_text(
            '@echo off\r\nsetlocal\r\ncd /d "%~dp0"\r\n'
            '"%~dp0python\\python.exe" -E -s "%~dp0backend\\portable_start.py"\r\n'
            'if errorlevel 1 pause\r\n',
            encoding="ascii", newline="",
        )
    else:
        launcher = stage / "Start.command"
        launcher.write_text(
            '#!/bin/sh\ncd "$(dirname "$0")" || exit 1\n'
            './python/bin/python3 -E -s ./backend/portable_start.py\n'
            'status=$?\n'
            'if [ "$status" -ne 0 ]; then printf "Нажмите Enter для закрытия..."; read -r _; fi\n'
            'exit "$status"\n',
            encoding="utf-8", newline="\n",
        )
        launcher.chmod(0o755)
    (stage / "README.txt").write_text(
        "UT112 — портативный офлайн-тренажёр\n\n"
        "Распакуйте архив целиком и запустите Start.cmd (Windows) или Start.command (macOS).\n"
        "Окно запуска оставьте открытым во время занятия. Enter в нём останавливает стенд.\n"
        "База и результаты сохраняются в профиле пользователя, отдельно от Docker.\n"
        "Участникам дайте адрес локальной сети, показанный в окне запуска.\n"
        "На macOS без Developer ID может понадобиться разрешить первый запуск в настройках безопасности.\n",
        encoding="utf-8",
    )
    (stage / "THIRD_PARTY.txt").write_text(
        "CPython standalone: https://github.com/astral-sh/python-build-standalone\n"
        "PostgreSQL binaries: https://github.com/zonkyio/embedded-postgres-binaries\n"
        "Dependency licenses are shipped in the Python and PostgreSQL runtime directories.\n",
        encoding="utf-8",
    )


def _zip_distribution(stage: Path) -> Path:
    archive = DIST / f"{stage.name}.zip"
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as output:
        for path in sorted(stage.rglob("*")):
            relative = path.relative_to(DIST).as_posix()
            if path.is_symlink():
                info = zipfile.ZipInfo(relative)
                info.create_system = 3
                info.external_attr = (stat.S_IFLNK | 0o777) << 16
                output.writestr(info, os.readlink(path))
            elif path.is_file():
                output.write(path, relative)
    return archive


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--target", choices=PLATFORMS, required=True)
    args = parser.parse_args()
    _assert_native(args.target)
    spec = PLATFORMS[args.target]
    DIST.mkdir(exist_ok=True)
    cache = DIST / "download-cache"
    stage = DIST / f"UT112-{args.target}"
    if stage.exists():
        shutil.rmtree(stage)
    stage.mkdir()

    python_name = (
        f"cpython-{PYTHON_VERSION}+{PYTHON_TAG}-{spec['python_target']}-install_only_stripped.tar.gz"
    )
    python_archive = _download(
        f"{PYTHON_BASE}/{python_name}", spec["python_sha256"], cache / python_name
    )
    with tarfile.open(python_archive, "r:gz") as archive:
        _safe_tar_extract(archive, stage)

    postgres_name = f"embedded-postgres-binaries-{spec['postgres_target']}"
    postgres_jar = _download(
        f"{POSTGRES_BASE}/{postgres_name}/{POSTGRES_VERSION}/{postgres_name}-{POSTGRES_VERSION}.jar",
        spec["postgres_sha256"],
        cache / f"{postgres_name}-{POSTGRES_VERSION}.jar",
    )
    with zipfile.ZipFile(postgres_jar) as source:
        files = [name for name in source.namelist() if name.endswith(".txz")]
        if len(files) != 1:
            raise RuntimeError("PostgreSQL archive has an unexpected structure")
        with tarfile.open(fileobj=io.BytesIO(source.read(files[0])), mode="r:xz") as archive:
            _safe_tar_extract(archive, stage / "postgres")

    _run("npm.cmd" if sys.platform == "win32" else "npm", "ci", cwd=ROOT / "frontend")
    _run("npm.cmd" if sys.platform == "win32" else "npm", "run", "build", cwd=ROOT / "frontend")
    _install_requirements(stage, cache, args.target)
    _copy_source(stage)
    _write_launchers(stage, args.target)
    manifest = {
        "target": args.target,
        "application": {"git_commit": (stage / "VERSION").read_text(encoding="utf-8").strip()},
        "python": {"version": PYTHON_VERSION, "sha256": spec["python_sha256"]},
        "postgres": {"version": POSTGRES_VERSION, "sha256": spec["postgres_sha256"]},
        "backend_lock_sha256": hashlib.sha256((ROOT / "backend" / "uv.lock").read_bytes()).hexdigest(),
        "frontend_lock_sha256": hashlib.sha256(
            (ROOT / "frontend" / "package-lock.json").read_bytes()
        ).hexdigest(),
    }
    (stage / "COMPONENTS.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    archive = _zip_distribution(stage)
    print(f"Built {archive} ({archive.stat().st_size} bytes)")


if __name__ == "__main__":
    main()

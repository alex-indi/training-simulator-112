"""Run the bundled demo without Docker, an installed Python, or internet access."""

from __future__ import annotations

import asyncio
import contextlib
import ipaddress
import json
import os
import secrets
import shutil
import socket
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
import webbrowser
from datetime import UTC, datetime
from pathlib import Path

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

BACKEND_ROOT = Path(__file__).resolve().parent
BUNDLE_ROOT = BACKEND_ROOT.parent
POSTGRES_ROOT = BUNDLE_ROOT / "postgres"
FRONTEND_ROOT = BUNDLE_ROOT / "frontend"
DATABASE_NAME = "training_simulator_112"
DATABASE_USER = "ut112"
POSTGRES_MAJOR = "16"


def data_directory() -> Path:
    override = os.environ.get("UT112_PORTABLE_DATA_DIR")
    if override:
        return Path(override).expanduser().resolve()
    if sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA")
        if not base:
            raise RuntimeError("Не найдена папка LOCALAPPDATA для хранения базы.")
        return Path(base) / "UT112"
    return Path.home() / "Library" / "Application Support" / "UT112"


def _write_private(path: Path, content: str) -> None:
    temporary = path.with_name(path.name + ".tmp")
    with temporary.open("w", encoding="utf-8", newline="\n") as stream:
        stream.write(content)
    if sys.platform != "win32":
        temporary.chmod(0o600)
    temporary.replace(path)


def _database_settings(home: Path) -> dict[str, str]:
    path = home / "database.json"
    cluster = home / "postgres"
    if path.exists():
        settings = json.loads(path.read_text(encoding="utf-8"))
        password = settings.get("password")
        if not isinstance(password, str) or len(password) < 32:
            raise RuntimeError("Файл настроек базы повреждён. Данные PostgreSQL сохранены.")
        return {"password": password}
    if cluster.exists():
        raise RuntimeError("Для существующей базы нет пароля. Данные PostgreSQL сохранены.")
    settings = {"password": secrets.token_hex(32)}
    _write_private(path, json.dumps(settings))
    return settings


def _postgres_binary(name: str) -> Path:
    suffix = ".exe" if sys.platform == "win32" else ""
    binary = POSTGRES_ROOT / "bin" / f"{name}{suffix}"
    if not binary.is_file():
        raise RuntimeError(f"В архиве отсутствует PostgreSQL: {binary}")
    return binary


def _postgres_environment() -> dict[str, str]:
    environment = os.environ.copy()
    environment["PATH"] = str(POSTGRES_ROOT / "bin") + os.pathsep + environment.get("PATH", "")
    if sys.platform == "darwin":
        environment["DYLD_LIBRARY_PATH"] = str(POSTGRES_ROOT / "lib")
    return environment


def _run_postgres_tool(
    name: str, *arguments: str, check: bool = True, capture_output: bool = True
) -> subprocess.CompletedProcess[str]:
    command = [str(_postgres_binary(name)), *arguments]
    result = subprocess.run(
        command,
        env=_postgres_environment(),
        stdout=subprocess.PIPE if capture_output else subprocess.DEVNULL,
        stderr=subprocess.PIPE if capture_output else subprocess.DEVNULL,
        text=True,
        errors="replace",
        check=False,
    )
    if check and result.returncode:
        raise RuntimeError(f"{name} завершился с ошибкой:\n{result.stderr or result.stdout}")
    return result


def _initialize_cluster(home: Path, password: str) -> None:
    cluster = home / "postgres"
    if cluster.exists():
        if (cluster / "PG_VERSION").read_text(encoding="ascii").strip() != POSTGRES_MAJOR:
            raise RuntimeError("Несовместимая версия PostgreSQL. Существующая база не изменена.")
        return
    pending = home / "postgres.init"
    if pending.exists():
        shutil.rmtree(pending)
    password_file = home / "init-password.tmp"
    try:
        _write_private(password_file, password + "\n")
        _run_postgres_tool(
            "initdb",
            "-D", str(pending),
            "-U", DATABASE_USER,
            "--auth=scram-sha-256",
            "--pwfile", str(password_file),
            "--encoding=UTF8",
            "--locale=C",
            "--no-instructions",
        )
        pending.replace(cluster)
    finally:
        password_file.unlink(missing_ok=True)


def _bundled_version() -> str:
    path = BUNDLE_ROOT / "VERSION"
    return path.read_text(encoding="utf-8").strip() if path.exists() else "development"


def _backup_before_upgrade(home: Path) -> None:
    version_file = home / "app-version"
    current = _bundled_version()
    previous = version_file.read_text(encoding="utf-8").strip() if version_file.exists() else ""
    if not previous or previous == current:
        return
    backup_root = home / "backups"
    backup_root.mkdir(exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    destination = backup_root / f"postgres-{stamp}-{previous[:12]}"
    print(f"Сохраняю резервную копию базы: {destination}", flush=True)
    shutil.copytree(home / "postgres", destination)


def _free_port(preferred: int = 0) -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", preferred))
        return int(listener.getsockname()[1])


def _running_postgres_port(home: Path) -> int | None:
    result = _run_postgres_tool("pg_ctl", "-D", str(home / "postgres"), "status", check=False)
    if result.returncode:
        return None
    lines = (home / "postgres" / "postmaster.pid").read_text(encoding="utf-8").splitlines()
    return int(lines[3])


def _start_postgres(home: Path) -> int:
    running_port = _running_postgres_port(home)
    if running_port is not None:
        print("Использую уже работающую локальную базу PostgreSQL.", flush=True)
        return running_port
    log = home / "logs" / "postgres.log"
    for _ in range(3):
        port = _free_port()
        result = _run_postgres_tool(
            "pg_ctl",
            "-D", str(home / "postgres"),
            "-l", str(log),
            "-o", f"-h 127.0.0.1 -p {port}",
            "-w", "-t", "30", "start",
            check=False,
            capture_output=False,
        )
        if result.returncode == 0:
            return port
    raise RuntimeError(f"PostgreSQL не запустился. Подробности: {log}")


def _stop_postgres(home: Path) -> None:
    if _running_postgres_port(home) is not None:
        _run_postgres_tool("pg_ctl", "-D", str(home / "postgres"), "-m", "fast", "-w", "stop")


async def _create_database(password: str, port: int) -> None:
    import asyncpg

    connection = await asyncpg.connect(
        host="127.0.0.1", port=port, user=DATABASE_USER, password=password, database="postgres"
    )
    try:
        exists = await connection.fetchval(
            "SELECT 1 FROM pg_database WHERE datname = $1", DATABASE_NAME
        )
        if not exists:
            await connection.execute(f"CREATE DATABASE {DATABASE_NAME}")
    finally:
        await connection.close()


async def _needs_seed(password: str, port: int) -> bool:
    import asyncpg

    connection = await asyncpg.connect(
        host="127.0.0.1", port=port, user=DATABASE_USER, password=password, database=DATABASE_NAME
    )
    try:
        return not await connection.fetchval(
            "SELECT EXISTS (SELECT 1 FROM users WHERE username = 'admin') "
            "AND EXISTS (SELECT 1 FROM scenario_templates) "
            "AND EXISTS (SELECT 1 FROM city_objects) "
            "AND EXISTS (SELECT 1 FROM dispatch_services)"
        )
    finally:
        await connection.close()


def _prepare_application(home: Path, password: str, port: int) -> None:
    os.environ["DATABASE_URL"] = (
        f"postgresql+asyncpg://{DATABASE_USER}:{password}@127.0.0.1:{port}/{DATABASE_NAME}"
    )
    os.environ["UT112_PORTABLE_DATA_DIR"] = str(home)
    os.environ["PORTABLE_MODE"] = "true"
    os.environ["AI_TEXT_ENABLED"] = "false"
    os.environ["AI_TEXT_PROVIDER"] = "template"
    os.environ.pop("AI_TEXT_API_KEY", None)
    os.environ.pop("OPENAI_API_KEY", None)
    asyncio.run(_create_database(password, port))

    from alembic import command
    from alembic.config import Config

    alembic = Config(str(BACKEND_ROOT / "alembic.ini"))
    alembic.set_main_option("script_location", str(BACKEND_ROOT / "migrations"))
    command.upgrade(alembic, "head")
    if asyncio.run(_needs_seed(password, port)):
        print("Загружаю демонстрационные данные (только при первом запуске)...", flush=True)
        from app.scripts.seed_all import seed_all

        asyncio.run(seed_all())
    _write_private(home / "app-version", _bundled_version() + "\n")


def _lan_addresses() -> list[str]:
    addresses: set[str] = set()
    with contextlib.suppress(OSError):
        for address in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ip = address[4][0]
            if ipaddress.ip_address(ip).is_private and not ip.startswith("127."):
                addresses.add(ip)
    return sorted(addresses)


def _web_port() -> int:
    for port in range(8080, 8100):
        with contextlib.suppress(OSError):
            return _free_port(port)
    return _free_port()


def _healthy(url: str) -> bool:
    try:
        with urllib.request.urlopen(url + "/health", timeout=2) as response:
            return response.status == 200
    except (OSError, urllib.error.URLError):
        return False


def _acquire_lock(home: Path):
    lock = (home / "launcher.lock").open("a+b")
    lock.seek(0, os.SEEK_END)
    if lock.tell() == 0:
        lock.write(b"0")
        lock.flush()
    lock.seek(0)
    try:
        if sys.platform == "win32":
            import msvcrt

            msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl

            fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        lock.close()
        return None
    return lock


def _open_running_instance(home: Path) -> None:
    instance = home / "instance.json"
    for _ in range(30):
        with contextlib.suppress(OSError, ValueError, KeyError):
            url = json.loads(instance.read_text(encoding="utf-8"))["url"]
            if url.startswith("http://127.0.0.1:") and _healthy(url):
                print(f"Тренажёр уже запущен: {url}")
                if not os.environ.get("UT112_PORTABLE_NO_BROWSER"):
                    webbrowser.open(url)
                return
        time.sleep(1)
    raise RuntimeError("Другой запуск ещё выполняется. Проверьте его окно и журнал.")


def _serve(home: Path, port: int, addresses: list[str]) -> None:
    import uvicorn

    server = uvicorn.Server(
        uvicorn.Config("app.main:socket_app", host="0.0.0.0", port=port, log_level="warning")
    )
    thread = threading.Thread(target=server.run, name="ut112-web")
    thread.start()
    local_url = f"http://127.0.0.1:{port}"
    instance = home / "instance.json"
    try:
        for _ in range(60):
            if _healthy(local_url):
                break
            if not thread.is_alive():
                raise RuntimeError("Веб-сервер завершился при запуске.")
            time.sleep(1)
        else:
            raise RuntimeError("Веб-сервер не ответил за 60 секунд.")
        _write_private(instance, json.dumps({"url": local_url}))
        print(f"Тренажёр готов: {local_url}")
        for address in addresses:
            print(f"Адрес для локальной сети: http://{address}:{port}")
        print("Разрешите доступ в локальной сети, если ОС покажет запрос файрвола.")
        print("Нажмите Enter в этом окне для остановки тренажёра.", flush=True)
        if not os.environ.get("UT112_PORTABLE_NO_BROWSER"):
            webbrowser.open(local_url)
        input()
    finally:
        instance.unlink(missing_ok=True)
        server.should_exit = True
        thread.join(timeout=20)


def main() -> int:
    home = data_directory()
    home.mkdir(parents=True, exist_ok=True)
    if sys.platform != "win32":
        home.chmod(0o700)
    (home / "logs").mkdir(exist_ok=True)
    lock = _acquire_lock(home)
    if lock is None:
        _open_running_instance(home)
        return 0
    database_started = False
    try:
        (home / "instance.json").unlink(missing_ok=True)
        settings = _database_settings(home)
        _initialize_cluster(home, settings["password"])
        if _running_postgres_port(home) is not None:
            _stop_postgres(home)
        _backup_before_upgrade(home)
        port = _start_postgres(home)
        database_started = True
        web_port = _web_port()
        addresses = _lan_addresses()
        origins = [f"http://{host}:{web_port}" for host in ("127.0.0.1", "localhost", *addresses)]
        os.environ["FRONTEND_ORIGINS"] = ",".join(origins)
        os.environ["UT112_PORTABLE_FRONTEND_DIR"] = str(FRONTEND_ROOT)
        _prepare_application(home, settings["password"], port)
        _serve(home, web_port, addresses)
        return 0
    finally:
        if database_started:
            _stop_postgres(home)
        lock.close()


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (KeyboardInterrupt, EOFError):
        print("Тренажёр остановлен.")
    except Exception as error:
        print(f"Ошибка запуска: {error}", file=sys.stderr)
        raise SystemExit(1) from error

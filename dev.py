"""Единая точка проверки окружения и локального запуска тренажёра."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import signal
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
import webbrowser
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

PROJECT_ROOT = Path(__file__).resolve().parent
BACKEND_DIR = PROJECT_ROOT / "backend"
FRONTEND_DIR = PROJECT_ROOT / "frontend"
STATE_DIR = PROJECT_ROOT / ".dev-state"
SHUTDOWN_TIMEOUT_SECONDS = 5
START_TIMEOUT_SECONDS = 20
REQUIRED_PATHS = (
    "backend",
    "frontend",
    "backend/pyproject.toml",
    "backend/uv.lock",
    "frontend/package.json",
    "frontend/package-lock.json",
)
INSTALL_URLS = {
    "git": "https://git-scm.com/downloads",
    "uv": "https://docs.astral.sh/uv/",
    "node": "https://nodejs.org/",
    "npm": "https://nodejs.org/",
}


class LauncherError(Exception):
    """User-facing startup failure."""


def message(level: str, value: str) -> None:
    print(f"[{level}] {value}", flush=True)


def env_values() -> dict[str, str]:
    values: dict[str, str] = {}
    file = PROJECT_ROOT / ".env"
    if file.is_file():
        for line in file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            key, separator, value = line.partition("=")
            if separator:
                values[key.strip()] = value.strip().strip("\"'")
    values.update(os.environ)
    return values


def dev_setting(name: str, fallback: str) -> str:
    return env_values().get(name, fallback)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Проверить окружение и запустить тренажёр.")
    parser.add_argument("--backend-host", default=dev_setting("BACKEND_HOST", "127.0.0.1"))
    parser.add_argument("--frontend-host", default=dev_setting("FRONTEND_HOST", "127.0.0.1"))
    parser.add_argument("--backend-port", type=int, default=int(dev_setting("BACKEND_PORT", "8000")))
    parser.add_argument("--frontend-port", type=int, default=int(dev_setting("FRONTEND_PORT", "5173")))
    parser.add_argument("--check", action="store_true", help="Проверить окружение без запуска сервисов.")
    parser.add_argument("--verbose", action="store_true", help="Показывать команды и подробные ошибки.")
    parser.add_argument("--non-interactive", action="store_true", help="Не задавать интерактивных вопросов.")
    parser.add_argument("--skip-sync", "--skip-install", action="store_true", dest="skip_sync")
    parser.add_argument("--seed-demo", action="store_true", help="Явно импортировать demo данные.")
    parser.add_argument("--require-current-main", action="store_true")
    parser.add_argument("--open", action="store_true", help="Открыть frontend в браузере.")
    return parser.parse_args(argv)


def preflight() -> None:
    if not PROJECT_ROOT.is_dir():
        raise LauncherError(f"Не найден корень проекта: {PROJECT_ROOT}")
    for path in REQUIRED_PATHS:
        if not (PROJECT_ROOT / path).exists():
            raise LauncherError(
                f"Не найден {path}.\nПроверьте, что команда запущена из корректной копии репозитория."
            )
    message("OK", "Файлы проекта найдены")


def commands() -> dict[str, str]:
    result = {}
    for name, install_url in INSTALL_URLS.items():
        resolved = shutil.which(name)
        if not resolved:
            raise LauncherError(
                f"Не найден {name}.\nУстановите {name}: {install_url}\n"
                "После установки снова выполните: python dev.py"
            )
        result[name] = resolved
    message("OK", "Системные зависимости найдены: git, uv, node, npm")
    return result


def safe_url(value: str) -> str:
    try:
        parsed = urlsplit(value)
        if parsed.password is None:
            return value
        host = parsed.hostname or ""
        if parsed.port:
            host += f":{parsed.port}"
        user = parsed.username or ""
        return urlunsplit((parsed.scheme, f"{user}:***@{host}", parsed.path, parsed.query, parsed.fragment))
    except ValueError:
        return "<скрыто>"


def redact(value: str) -> str:
    settings = env_values()
    for key in ("DATABASE_URL", "OPENAI_API_KEY", "AI_TEXT_API_KEY", "WEEEK_API_TOKEN", "MOS_API_KEY"):
        secret = settings.get(key, "")
        if secret:
            value = value.replace(secret, safe_url(secret) if key == "DATABASE_URL" else "***")
    try:
        password = urlsplit(settings.get("DATABASE_URL", "")).password
        if password:
            value = value.replace(password, "***")
    except ValueError:
        pass
    return value


def run_command(command: list[str], cwd: Path, args: argparse.Namespace) -> str:
    if args.verbose:
        message("INFO", f"Command: {' '.join(command)}")
    try:
        result = subprocess.run(command, cwd=cwd, text=True, capture_output=True, check=False)
    except OSError as error:
        raise LauncherError(f"Не удалось запустить {command[0]}: {error}") from error
    output = (result.stdout + "\n" + result.stderr).strip()
    if args.verbose and output:
        print(redact(output), flush=True)
    if result.returncode:
        lines = [line.strip() for line in output.splitlines() if line.strip()]
        useful = next(
            (line for line in reversed(lines) if "Error:" in line or "Exception:" in line),
            lines[-1] if lines else "нет подробностей",
        )
        raise LauncherError(f"Команда {' '.join(command[:3])} завершилась с ошибкой.\n{redact(useful)}")
    return result.stdout.strip()


def git_diagnostics(git: str, args: argparse.Namespace) -> None:
    def git_output(*parts: str) -> str:
        return run_command([git, *parts], PROJECT_ROOT, args).strip()

    branch = git_output("branch", "--show-current") or "(detached HEAD)"
    commit = git_output("rev-parse", "--short", "HEAD")
    state = git_output("status", "--porcelain")
    message("INFO", f"Git: {branch} @ {commit}; рабочее дерево {'изменено' if state else 'чистое'}")
    conflicts = git_output("diff", "--name-only", "--diff-filter=U")
    if conflicts:
        raise LauncherError(f"Обнаружены неразрешённые Git-конфликты:\n{conflicts}\nЗавершите или отмените merge перед запуском.")
    tracking = subprocess.run(
        [git, "rev-parse", "--verify", "origin/main"], cwd=PROJECT_ROOT,
        text=True, capture_output=True, check=False,
    )
    if tracking.returncode:
        message("WARN", "origin/main недоступен; Git не обновляется автоматически")
        return
    counts = git_output("rev-list", "--left-right", "--count", "HEAD...origin/main").split()
    if len(counts) == 2:
        ahead, behind = map(int, counts)
        message("INFO", f"Относительно origin/main: впереди {ahead}, позади {behind}")
        if branch == "main" and behind:
            message("WARN", f"Локальный main отстаёт от origin/main на {behind} commit. Выполните git pull или продолжите текущую версию.")
            if args.require_current_main:
                raise LauncherError("Требуется актуальная main; выполните git pull.")


def ensure_env(args: argparse.Namespace) -> dict[str, str]:
    file = PROJECT_ROOT / ".env"
    if not file.exists():
        message("WARN", ".env отсутствует")
        example = PROJECT_ROOT / ".env.example"
        if not args.non_interactive and sys.stdin.isatty() and example.is_file():
            answer = input("Создать локальный .env из .env.example? [Y/n] ").strip().lower()
            if answer in ("", "y", "yes", "д", "да"):
                shutil.copyfile(example, file)
                message("OK", ".env создан из .env.example")
        if not file.exists():
            message("INFO", "Создайте .env из .env.example или задайте настройки через переменные окружения")
    values = env_values()
    for name in ("DATABASE_URL", "FRONTEND_ORIGINS"):
        if not values.get(name):
            raise LauncherError(f"Не задана обязательная переменная {name}. Проверьте .env.")
    if values.get("AI_TEXT_ENABLED", "").lower() in ("1", "true", "yes"):
        provider = values.get("AI_TEXT_PROVIDER", "openai")
        missing = not values.get("AI_TEXT_MODEL")
        if provider == "openai":
            missing |= not (values.get("AI_TEXT_API_KEY") or values.get("OPENAI_API_KEY"))
        elif provider == "openai_compatible":
            missing |= not values.get("AI_TEXT_BASE_URL")
        else:
            missing = True
        if missing:
            fallback = values.get("AI_TEXT_FALLBACK_ENABLED", "true").lower() in ("1", "true", "yes")
            advice = "Будет использован fallback." if fallback else "Генерация текста может завершаться ошибкой."
            message("WARN", f"AI Text Renderer настроен не полностью; проверьте модель, провайдер и ключ. {advice}")
    message("OK", "Конфигурация проверена")
    if args.verbose:
        message("INFO", f"DATABASE_URL: {safe_url(values['DATABASE_URL'])}")
    return values


def sync_dependencies(uv: str, npm: str, args: argparse.Namespace) -> None:
    if args.skip_sync:
        message("WARN", "Синхронизация зависимостей пропущена")
        return
    try:
        run_command([uv, "sync", "--frozen"], BACKEND_DIR, args)
    except LauncherError as error:
        raise LauncherError(f"Python dependencies cannot be synchronized.\n{error}") from error
    message("OK", "Backend dependencies synchronized")

    lock = FRONTEND_DIR / "package-lock.json"
    fingerprint = hashlib.sha256(lock.read_bytes()).hexdigest()
    stamp = STATE_DIR / "frontend-lock.sha256"
    installed = (FRONTEND_DIR / "node_modules").is_dir()
    if installed and stamp.is_file() and stamp.read_text(encoding="ascii").strip() == fingerprint:
        message("OK", "Frontend dependencies unchanged")
        return
    message("INFO", "package-lock.json изменился или node_modules отсутствует; выполняю npm ci")
    try:
        run_command([npm, "ci"], FRONTEND_DIR, args)
    except LauncherError as error:
        raise LauncherError(f"Frontend dependency installation failed.\n{error}") from error
    STATE_DIR.mkdir(exist_ok=True)
    stamp.write_text(fingerprint + "\n", encoding="ascii")
    message("OK", "Frontend dependencies synchronized")


def database_status(uv: str, args: argparse.Namespace, references: bool = False) -> dict[str, object]:
    command = [uv, "run", "--no-sync", "python", "-m", "app.scripts.dev_diagnostics"]
    if references:
        command.append("--references")
    try:
        output = run_command(command, BACKEND_DIR, args)
        return json.loads(output.splitlines()[-1])
    except (LauncherError, ValueError, IndexError) as error:
        url = safe_url(env_values().get("DATABASE_URL", ""))
        raise LauncherError(
            f"PostgreSQL недоступен или его состояние не удалось проверить.\nDATABASE_URL: {url}\n"
            "Проверьте PostgreSQL/Docker, наличие БД и логин/пароль в .env.\n"
            f"Причина: {error}"
        ) from error


def prepare_database(uv: str, args: argparse.Namespace) -> None:
    status = database_status(uv, args)
    message("OK", "PostgreSQL доступен")
    if status["current"] != status["head"]:
        message("INFO", f"Требуются миграции: {status['current'] or '(пустая БД)'} → {status['head']}")
        try:
            run_command([uv, "run", "--no-sync", "alembic", "upgrade", "head"], BACKEND_DIR, args)
        except LauncherError as error:
            raise LauncherError(f"Database migration failed. Backend was not started.\n{error}") from error
    message("OK", "Database schema up to date")
    status = database_status(uv, args, references=True)
    missing = status.get("missing_references", [])
    core_missing = [name for name in missing if name != "users"]
    if core_missing:
        message("INFO", f"Отсутствуют обязательные данные: {', '.join(core_missing)}; импортирую CORE seed")
        try:
            run_command([uv, "run", "--no-sync", "python", "-m", "app.scripts.seed_core"], BACKEND_DIR, args)
        except LauncherError as error:
            raise LauncherError(f"Не удалось импортировать обязательные справочники.\n{error}") from error
        missing = database_status(uv, args, references=True).get("missing_references", [])
    if args.seed_demo:
        run_command([uv, "run", "--no-sync", "python", "-m", "app.scripts.seed_demo"], BACKEND_DIR, args)
        message("OK", "Demo данные импортированы")
        missing = database_status(uv, args, references=True).get("missing_references", [])
    if missing:
        advice = " Выполните python dev.py --seed-demo." if missing == ["users"] else ""
        raise LauncherError(f"Отсутствуют обязательные данные: {', '.join(missing)}.{advice}")
    message("OK", "Обязательные справочники доступны")


def check_port(host: str, port: int, service: str) -> None:
    if not 1 <= port <= 65535:
        raise LauncherError(f"Некорректный порт: {port}")
    bind_host = "0.0.0.0" if host == "0.0.0.0" else host
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.bind((bind_host, port))
    except OSError as error:
        raise LauncherError(
            f"Port {port} is already in use or unavailable ({error}).\n"
            f"Остановите старый процесс или укажите другой порт: python dev.py --{service}-port <порт>"
        ) from error


def start_process(command: list[str], cwd: Path) -> subprocess.Popen[bytes]:
    options: dict[str, object] = {"cwd": cwd}
    if os.name == "nt":
        options["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        options["start_new_session"] = True
    return subprocess.Popen(command, **options)


def stop_process(process: subprocess.Popen[bytes]) -> None:
    if process.poll() is not None:
        return
    if os.name == "nt":
        process.send_signal(signal.CTRL_BREAK_EVENT)
    else:
        os.killpg(process.pid, signal.SIGTERM)
    try:
        process.wait(timeout=SHUTDOWN_TIMEOUT_SECONDS)
    except subprocess.TimeoutExpired:
        if os.name == "nt":
            process.kill()
        else:
            os.killpg(process.pid, signal.SIGKILL)
        process.wait()


def wait_ready(process: subprocess.Popen[bytes], url: str, label: str) -> None:
    deadline = time.monotonic() + START_TIMEOUT_SECONDS
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise LauncherError(f"{label} завершился во время запуска (код {process.returncode}).")
        try:
            with urllib.request.urlopen(url, timeout=1) as response:
                if 200 <= response.status < 400:
                    message("OK", f"{label} готов")
                    return
        except (urllib.error.URLError, TimeoutError, OSError):
            pass
        time.sleep(0.2)
    raise LauncherError(f"{label} не стал доступен за {START_TIMEOUT_SECONDS} секунд: {url}")


def run_services(uv: str, npm: str, args: argparse.Namespace) -> int:
    backend_probe_host = "127.0.0.1" if args.backend_host == "0.0.0.0" else args.backend_host
    frontend_probe_host = "127.0.0.1" if args.frontend_host == "0.0.0.0" else args.frontend_host
    backend_url = f"http://{backend_probe_host}:{args.backend_port}/health"
    frontend_url = f"http://{frontend_probe_host}:{args.frontend_port}/"
    backend = start_process(
        [uv, "run", "--no-sync", "uvicorn", "app.main:socket_app", "--reload", "--host", args.backend_host, "--port", str(args.backend_port)],
        BACKEND_DIR,
    )
    processes = [backend]
    interrupted = False
    try:
        wait_ready(backend, backend_url, "Backend")
        frontend = start_process(
            [npm, "run", "dev", "--", "--strictPort", "--host", args.frontend_host, "--port", str(args.frontend_port)],
            FRONTEND_DIR,
        )
        processes.append(frontend)
        wait_ready(frontend, frontend_url, "Frontend")
        message("READY", f"Тренажёр доступен: {frontend_url}")
        if args.open:
            webbrowser.open(frontend_url)
        while all(process.poll() is None for process in processes):
            time.sleep(0.2)
        raise LauncherError("Один из сервисов завершился; второй остановлен.")
    except KeyboardInterrupt:
        interrupted = True
        message("INFO", "Останавливаю приложение...")
    finally:
        for process in reversed(processes):
            stop_process(process)
    return 0 if interrupted else 1


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        preflight()
        available = commands()
        git_diagnostics(available["git"], args)
        ensure_env(args)
        sync_dependencies(available["uv"], available["npm"], args)
        prepare_database(available["uv"], args)
        check_port(args.backend_host, args.backend_port, "backend")
        check_port(args.frontend_host, args.frontend_port, "frontend")
        message("OK", "Порты доступны")
        if args.check:
            message("READY", "Environment is ready.")
            return 0
        return run_services(available["uv"], available["npm"], args)
    except LauncherError as error:
        message("ERROR", str(error))
        return 1
    except Exception as error:  # noqa: BLE001 - normal mode must never print a traceback
        message("ERROR", f"Неожиданная ошибка: {redact(str(error))}")
        if args.verbose:
            import traceback
            print(redact(traceback.format_exc()), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

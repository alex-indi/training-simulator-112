"""Запускает backend и frontend тренажёра одной командой."""

from __future__ import annotations

import argparse
import os
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
BACKEND_DIR = PROJECT_ROOT / "backend"
FRONTEND_DIR = PROJECT_ROOT / "frontend"
SHUTDOWN_TIMEOUT_SECONDS = 5


def parse_args() -> argparse.Namespace:
    """Читает параметры локального запуска."""
    parser = argparse.ArgumentParser(
        description="Запустить FastAPI backend и Vite frontend.",
    )
    parser.add_argument("--backend-port", type=int, default=8000)
    parser.add_argument("--frontend-port", type=int, default=5173)
    parser.add_argument(
        "--skip-install",
        action="store_true",
        help="Не устанавливать отсутствующие зависимости перед запуском.",
    )
    return parser.parse_args()


def resolve_command(name: str) -> str:
    """Возвращает полный путь к команде или завершает запуск с подсказкой."""
    executable = shutil.which(name)
    if executable is None:
        raise RuntimeError(f"Команда '{name}' не найдена в PATH.")
    return executable


def install_dependencies(uv_command: str, npm_command: str) -> None:
    """Устанавливает зависимости только при отсутствии локальных каталогов."""
    if not (BACKEND_DIR / ".venv").is_dir():
        print("[setup] Устанавливаю зависимости backend...", flush=True)
        subprocess.run([uv_command, "sync"], cwd=BACKEND_DIR, check=True)

    if not (FRONTEND_DIR / "node_modules").is_dir():
        print("[setup] Устанавливаю зависимости frontend...", flush=True)
        subprocess.run([npm_command, "install"], cwd=FRONTEND_DIR, check=True)


def start_process(command: list[str], cwd: Path) -> subprocess.Popen[bytes]:
    """Запускает сервис в отдельной группе процессов для общего завершения."""
    options: dict[str, object] = {"cwd": cwd}
    if os.name == "nt":
        options["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        options["start_new_session"] = True
    return subprocess.Popen(command, **options)


def stop_process(process: subprocess.Popen[bytes]) -> None:
    """Корректно завершает сервис и его дочерние процессы."""
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


def run_services(args: argparse.Namespace) -> int:
    """Запускает оба сервиса и останавливает второй при завершении первого."""
    uv_command = resolve_command("uv")
    npm_command = resolve_command("npm")

    if not args.skip_install:
        install_dependencies(uv_command, npm_command)

    backend_command = [
        uv_command,
        "run",
        "uvicorn",
        "app.main:socket_app",
        "--reload",
        "--host",
        "127.0.0.1",
        "--port",
        str(args.backend_port),
    ]
    frontend_command = [
        npm_command,
        "run",
        "dev",
        "--",
        "--host",
        "127.0.0.1",
        "--port",
        str(args.frontend_port),
    ]

    print(f"[dev] Backend:  http://127.0.0.1:{args.backend_port}", flush=True)
    print(f"[dev] Frontend: http://127.0.0.1:{args.frontend_port}", flush=True)
    print("[dev] Для остановки нажмите Ctrl+C.\n", flush=True)

    backend = start_process(backend_command, BACKEND_DIR)
    frontend = start_process(frontend_command, FRONTEND_DIR)
    processes = [backend, frontend]
    interrupted = False

    try:
        while all(process.poll() is None for process in processes):
            time.sleep(0.2)
    except KeyboardInterrupt:
        interrupted = True
        print("\n[dev] Останавливаю приложение...", flush=True)
    finally:
        for process in processes:
            stop_process(process)

    if interrupted:
        return 0

    return next(
        (process.returncode for process in processes if process.returncode not in (0, -15)),
        0,
    )


def main() -> int:
    """Выполняет единый сценарий локального запуска."""
    try:
        return run_services(parse_args())
    except (RuntimeError, subprocess.CalledProcessError) as error:
        print(f"[dev] Ошибка: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

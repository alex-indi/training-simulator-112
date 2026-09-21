"""Проверки единого сценария локального запуска."""

import argparse

import dev


class FakeProcess:
    """Минимальная модель дочернего процесса для проверки shutdown-flow."""

    returncode: int | None = None

    def poll(self) -> None:
        """Сообщает, что процесс работает до начала остановки."""
        return None


def test_keyboard_interrupt_is_successful_shutdown(monkeypatch) -> None:
    """Остановка через Ctrl+C возвращает успешный код независимо от сигналов детям."""
    processes = [FakeProcess(), FakeProcess()]

    monkeypatch.setattr(dev, "resolve_command", lambda name: name)
    monkeypatch.setattr(dev, "start_process", lambda command, cwd: processes.pop(0))
    monkeypatch.setattr(
        dev.time,
        "sleep",
        lambda seconds: (_ for _ in ()).throw(KeyboardInterrupt),
    )

    stopped_processes: list[FakeProcess] = []

    def stop_process(process: FakeProcess) -> None:
        """Имитирует принудительное завершение дочернего процесса."""
        process.returncode = -9
        stopped_processes.append(process)

    monkeypatch.setattr(dev, "stop_process", stop_process)

    exit_code = dev.run_services(
        argparse.Namespace(skip_install=True, backend_port=8000, frontend_port=5173),
    )

    assert exit_code == 0
    assert len(stopped_processes) == 2

"""Exercise an extracted portable archive with an isolated persistent profile."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
import zipfile
from pathlib import Path


def _request(url: str) -> bytes:
    with urllib.request.urlopen(url, timeout=3) as response:
        if response.status != 200:
            raise AssertionError(f"{url}: HTTP {response.status}")
        return response.read()


def _wait_ready(profile: Path, process: subprocess.Popen, log: Path) -> str:
    for _ in range(600):
        if process.poll() is not None:
            raise AssertionError(f"Launcher exited {process.returncode}:\n{log.read_text(errors='replace')}")
        try:
            instance = profile / "instance.json"
            if instance.stat().st_mtime < process.launch_started:
                time.sleep(1)
                continue
            url = json.loads(instance.read_text())["url"]
            if json.loads(_request(url + "/health"))["status"] == "ok":
                return url
        except (OSError, KeyError, ValueError, urllib.error.URLError):
            pass
        time.sleep(1)
    raise AssertionError(f"Launcher timed out:\n{log.read_text(errors='replace')}")


def _database_marker(python: Path, profile: Path, action: str) -> None:
    code = """
import asyncio, asyncpg, json, sys
from pathlib import Path
p = Path(sys.argv[1]); action = sys.argv[2]
password = json.loads((p / 'database.json').read_text())['password']
port = int((p / 'postgres' / 'postmaster.pid').read_text().splitlines()[3])
async def main():
    db = await asyncpg.connect(host='127.0.0.1', port=port, user='ut112',
        password=password, database='training_simulator_112')
    try:
        if action == 'create':
            await db.execute('CREATE TABLE portable_smoke_marker (value TEXT NOT NULL)')
            await db.execute("INSERT INTO portable_smoke_marker VALUES ('persisted')")
        else:
            assert await db.fetchval('SELECT value FROM portable_smoke_marker') == 'persisted'
    finally:
        await db.close()
asyncio.run(main())
"""
    subprocess.run([str(python), "-E", "-s", "-c", code, str(profile), action], check=True)


def _start(bundle: Path, profile: Path, log: Path, *, direct: bool = False) -> subprocess.Popen:
    launcher = bundle / ("Start.cmd" if sys.platform == "win32" else "Start.command")
    command = ["cmd", "/c", str(launcher)] if sys.platform == "win32" else ["sh", str(launcher)]
    if direct:
        python = bundle / "python" / ("python.exe" if sys.platform == "win32" else "bin/python3")
        command = [str(python), "-E", "-s", str(bundle / "backend" / "portable_start.py")]
    environment = os.environ.copy()
    environment["UT112_PORTABLE_DATA_DIR"] = str(profile)
    environment["UT112_PORTABLE_NO_BROWSER"] = "1"
    output = log.open("ab")
    try:
        launch_started = time.time()
        process = subprocess.Popen(
            command,
            cwd=bundle,
            env=environment,
            stdin=subprocess.PIPE,
            stdout=output,
            stderr=subprocess.STDOUT,
            creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if sys.platform == "win32" else 0,
            start_new_session=sys.platform != "win32",
        )
    finally:
        output.close()
    process.launch_started = launch_started
    return process


def _abort(process: subprocess.Popen, bundle: Path, profile: Path) -> None:
    if process.poll() is None:
        if sys.platform == "win32":
            subprocess.run(
                ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
            )
        else:
            os.killpg(process.pid, signal.SIGTERM)
        process.wait(timeout=15)
    cluster = profile / "postgres"
    binary = bundle / "postgres" / "bin" / (
        "pg_ctl.exe" if sys.platform == "win32" else "pg_ctl"
    )
    if cluster.exists() and binary.is_file():
        environment = os.environ.copy()
        environment["PATH"] = str(binary.parent) + os.pathsep + environment.get("PATH", "")
        if sys.platform == "darwin":
            environment["DYLD_LIBRARY_PATH"] = str(bundle / "postgres" / "lib")
        subprocess.run(
            [str(binary), "-D", str(cluster), "-m", "fast", "-w", "stop"],
            env=environment,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
            timeout=30,
        )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("archive", type=Path)
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix="UT112 portable smoke ") as temporary:
        root = Path(temporary)
        if sys.platform == "darwin":
            subprocess.run(["unzip", "-q", str(args.archive.resolve()), "-d", str(root)], check=True)
        else:
            with zipfile.ZipFile(args.archive) as archive:
                archive.extractall(root)
        bundle = root / args.archive.stem
        profile = root / "separate profile"
        log = root / "launcher.log"
        python = bundle / "python" / ("python.exe" if sys.platform == "win32" else "bin/python3")
        launcher = bundle / ("Start.cmd" if sys.platform == "win32" else "Start.command")
        assert launcher.is_file() and python.is_file()
        with socket.socket() as occupied:
            occupied.bind(("127.0.0.1", 8080))
            occupied.listen()
            first = _start(bundle, profile, log)
            try:
                url = _wait_ready(profile, first, log)
                assert not url.endswith(":8080"), url
                assert b'<div id="root">' in _request(url + "/")
                assert b'<div id="root">' in _request(url + "/admin")
                assert _request(url + "/socket.io/?EIO=4&transport=polling").startswith(b"0")
                try:
                    _request(url + "/api/no-such-route")
                except urllib.error.HTTPError as error:
                    assert error.code == 404
                else:
                    raise AssertionError("Unknown API route returned the frontend")
                _database_marker(python, profile, "create")
                second = _start(bundle, profile, root / "second.log")
                assert second.wait(timeout=15) == 0
                assert json.loads((profile / "instance.json").read_text())["url"] == url
                first.stdin.write(b"\n")
                first.stdin.flush()
                assert first.wait(timeout=30) == 0
            finally:
                _abort(first, bundle, profile)
        moved = root / "moved bundle with spaces"
        shutil.move(bundle, moved)
        python = moved / "python" / ("python.exe" if sys.platform == "win32" else "bin/python3")
        restart = _start(moved, profile, log)
        try:
            url = _wait_ready(profile, restart, log)
            _database_marker(python, profile, "check")
            assert b'<div id="root">' in _request(url + "/")
            restart.stdin.write(b"\n")
            restart.stdin.flush()
            assert restart.wait(timeout=30) == 0
        finally:
            _abort(restart, moved, profile)
        crashed = _start(moved, profile, log, direct=True)
        _wait_ready(profile, crashed, log)
        crashed.kill()
        crashed.wait(timeout=15)
        recovered = _start(moved, profile, log)
        try:
            url = _wait_ready(profile, recovered, log)
            _database_marker(python, profile, "check")
            assert b'<div id="root">' in _request(url + "/")
            recovered.stdin.write(b"\n")
            recovered.stdin.flush()
            assert recovered.wait(timeout=30) == 0
        finally:
            _abort(recovered, moved, profile)
        print(f"Portable smoke passed: {args.archive.name}")


if __name__ == "__main__":
    main()

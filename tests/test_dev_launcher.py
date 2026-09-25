"""Regression checks for the repository launcher without external services."""

import argparse
import hashlib
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import dev


class DependencySyncTests(unittest.TestCase):
    def test_changed_lock_reinstalls_even_when_node_modules_exists(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            backend = root / "backend"
            frontend = root / "frontend"
            state = root / ".dev-state"
            backend.mkdir()
            frontend.mkdir()
            (frontend / "node_modules").mkdir()
            state.mkdir()
            lock = frontend / "package-lock.json"
            lock.write_text('{"packages":{"new-font":{}}}', encoding="utf-8")
            (state / "frontend-lock.sha256").write_text("old-hash\n", encoding="ascii")
            calls = []

            def run(command, cwd, args):
                calls.append((command, cwd))
                return ""

            with (
                patch.object(dev, "BACKEND_DIR", backend),
                patch.object(dev, "FRONTEND_DIR", frontend),
                patch.object(dev, "STATE_DIR", state),
                patch.object(dev, "run_command", side_effect=run),
            ):
                args = argparse.Namespace(skip_sync=False, verbose=False)
                dev.sync_dependencies("uv", "npm", args)
                self.assertEqual(calls, [
                    (["uv", "sync", "--frozen"], backend),
                    (["npm", "ci"], frontend),
                ])
                self.assertEqual(
                    (state / "frontend-lock.sha256").read_text(encoding="ascii").strip(),
                    hashlib.sha256(lock.read_bytes()).hexdigest(),
                )
                calls.clear()
                dev.sync_dependencies("uv", "npm", args)
                self.assertEqual(calls, [(["uv", "sync", "--frozen"], backend)])


if __name__ == "__main__":
    unittest.main()

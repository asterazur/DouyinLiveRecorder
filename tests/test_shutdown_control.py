"""Self-contained tests for DLR's local shutdown protocol.

Run: python -m unittest discover -s tests -p 'test_shutdown_control.py'
"""
import ast
import json
import os
from pathlib import Path
import tempfile
import threading
import unittest

from shutdown_control import (
    ShutdownControlServer,
    descriptor_path,
    request_shutdown,
    shutdown_cli,
)


class ShutdownControlTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.shutdown_received = threading.Event()
        self.shutdown_reasons = []
        self.server = ShutdownControlServer(
            self.temporary.name,
            self._on_stop,
        )
        self.server.start()

    def tearDown(self):
        self.server.close()
        self.temporary.cleanup()

    def _on_stop(self, reason):
        self.shutdown_reasons.append(reason)
        self.shutdown_received.set()

    def test_shutdown_one_instance(self):
        reply = request_shutdown(self.temporary.name, os.getpid())
        self.assertEqual(reply["status"], "accepted")
        self.assertEqual(reply["pid"], os.getpid())
        self.assertTrue(self.shutdown_received.wait(2))
        self.assertEqual(self.shutdown_reasons, ["external_request"])

    def test_cli_stop(self):
        result = shutdown_cli(
            ["--stop", "--pid", str(os.getpid())],
            self.temporary.name,
        )
        self.assertEqual(result, 0)
        self.assertTrue(self.shutdown_received.wait(2))

    def test_wrong_token_is_rejected(self):
        location = descriptor_path(self.temporary.name, os.getpid())
        with open(location, "r", encoding="utf-8") as handle:
            state = json.load(handle)
        state["token"] = "0" * 64 if state["token"] != "0" * 64 else "1" * 64
        with open(location, "w", encoding="utf-8") as handle:
            json.dump(state, handle)
        with self.assertRaises(RuntimeError):
            request_shutdown(self.temporary.name, os.getpid())
        self.assertFalse(self.shutdown_received.is_set())

    def test_wrong_installation_cannot_address_recorder(self):
        with tempfile.TemporaryDirectory() as other_installation:
            with self.assertRaises(FileNotFoundError):
                request_shutdown(other_installation, os.getpid())
        self.assertFalse(self.shutdown_received.is_set())

    def test_stale_descriptor_cannot_be_used_after_close(self):
        location = descriptor_path(self.temporary.name, os.getpid())
        self.assertTrue(os.path.isfile(location))
        self.server.close()
        self.assertFalse(os.path.exists(location))
        with self.assertRaises(FileNotFoundError):
            request_shutdown(self.temporary.name, os.getpid())

    def test_python_sources_parse(self):
        project = Path(__file__).resolve().parents[1]
        for filename in ("main.py", "shutdown_control.py", "runtime_events.py"):
            with self.subTest(filename=filename):
                ast.parse((project / filename).read_text(encoding="utf-8-sig"))


if __name__ == "__main__":
    unittest.main()

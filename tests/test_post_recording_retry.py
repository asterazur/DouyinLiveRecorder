"""Regression checks for the existing one-shot post-recording recheck.

The recorder's main.py executes platform startup at import time. Inspect and
execute only its retry selector AST, rather than importing that module.

Run: python -m unittest discover -s tests -p 'test_post_recording_retry.py'
"""
import ast
from pathlib import Path
from types import SimpleNamespace
import unittest


class PostRecordingRetryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        source = (Path(__file__).resolve().parents[1] / "main.py").read_text(
            encoding="utf-8-sig"
        )
        cls.worker = next(
            node for node in ast.parse(source).body
            if isinstance(node, ast.FunctionDef) and node.name == "start_record"
        )
        retry_blocks = [
            node for node in ast.walk(cls.worker)
            if isinstance(node, ast.If)
            and isinstance(node.test, ast.Name)
            and node.test.id == "record_finished"
        ]
        if len(retry_blocks) != 1:
            raise AssertionError("Expected one post-recording delay selector")
        cls.retry_code = compile(
            ast.fix_missing_locations(
                ast.Module(body=retry_blocks, type_ignores=[])
            ),
            "<post-recording-retry>",
            "exec",
        )

    @staticmethod
    def _is_named_assignment(statement, name):
        return (
            isinstance(statement, ast.Assign)
            and len(statement.targets) == 1
            and isinstance(statement.targets[0], ast.Name)
            and statement.targets[0].id == name
        )

    def test_each_ffmpeg_path_marks_a_natural_exit_for_quick_recheck(self):
        """All FFmpeg formats must arm the retry, but not on forced shutdown."""
        call_sites = 0
        for parent in ast.walk(self.worker):
            for _, statements in ast.iter_fields(parent):
                if not isinstance(statements, list):
                    continue
                for index, statement in enumerate(statements):
                    if not self._is_named_assignment(statement, "comment_end"):
                        continue
                    call = statement.value
                    if not (
                        isinstance(call, ast.Call)
                        and isinstance(call.func, ast.Name)
                        and call.func.id == "check_subprocess"
                    ):
                        continue
                    call_sites += 1
                    self.assertGreaterEqual(
                        len(statements), index + 3,
                        "FFmpeg call needs completion flag and stop handler"
                    )
                    mark = statements[index + 1]
                    self.assertTrue(
                        self._is_named_assignment(mark, "record_finished"),
                        f"Missing recording-finished flag after line {statement.lineno}",
                    )
                    self.assertIsInstance(mark.value, ast.UnaryOp)
                    self.assertIsInstance(mark.value.op, ast.Not)
                    self.assertIsInstance(mark.value.operand, ast.Name)
                    self.assertEqual(mark.value.operand.id, "comment_end")
                    stop = statements[index + 2]
                    self.assertIsInstance(stop, ast.If)
                    self.assertIsInstance(stop.test, ast.Name)
                    self.assertEqual(stop.test.id, "comment_end")
                    self.assertTrue(
                        any(isinstance(n, ast.Return) for n in ast.walk(stop)),
                        "Deliberate disable/shutdown must still exit"
                    )
        self.assertGreaterEqual(call_sites, 6)

    def _retry(self, finished, elapsed, normal_delay=210):
        context = {
            "record_finished": finished,
            "count_time": 100.0,
            "num": normal_delay,
            "x": normal_delay,
            "time": SimpleNamespace(time=lambda: 100.0 + elapsed),
        }
        exec(self.retry_code, {}, context)
        return context["x"], context["record_finished"]

    def test_one_fast_check_then_normal_interval(self):
        self.assertEqual(self._retry(True, 20), (30, False))
        self.assertEqual(self._retry(False, 20), (210, False))

    def test_only_recent_completion_uses_fast_check(self):
        self.assertEqual(self._retry(True, 59.9), (30, False))
        self.assertEqual(self._retry(True, 60), (210, False))
        self.assertEqual(self._retry(True, 120), (210, False))

    def test_normal_offline_monitoring_keeps_configured_delay(self):
        self.assertEqual(self._retry(False, 0, 150), (150, False))


if __name__ == "__main__":
    unittest.main()

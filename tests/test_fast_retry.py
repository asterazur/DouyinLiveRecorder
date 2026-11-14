"""Unit tests for bounded per-room retry and recorder backend hooks."""
import ast
from pathlib import Path
import unittest
from fast_retry import FastRetryWindow


class Clock:
    def __init__(self, now=100.0):
        self.now = now

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += seconds


class FastRetryTests(unittest.TestCase):
    def setUp(self):
        self.clock = Clock()
        self.retry = FastRetryWindow(True, 30, 300, 900, clock=self.clock)

    def test_offline_monitoring_is_not_accelerated_without_recording(self):
        self.assertEqual(self.retry.next_delay(210), 210)
        self.assertFalse(self.retry.window_active())

    def test_bounded_window_and_boundary(self):
        self.assertTrue(self.retry.recording_ended())
        self.assertEqual(self.retry.next_delay(210), 30)
        self.clock.advance(280)
        self.assertEqual(self.retry.next_delay(210), 20)
        self.clock.advance(20)
        self.assertEqual(self.retry.next_delay(210), 210)

    def test_repeated_failures_do_not_extend_window_or_bypass_cooldown(self):
        self.assertTrue(self.retry.recording_ended())
        self.clock.advance(299)
        self.assertFalse(self.retry.recording_ended())
        self.clock.advance(1)
        self.assertFalse(self.retry.recording_ended())
        self.assertEqual(self.retry.next_delay(210), 210)
        self.clock.advance(899)
        self.assertFalse(self.retry.recording_ended())
        self.clock.advance(1)
        self.assertTrue(self.retry.recording_ended())
        self.assertEqual(self.retry.next_delay(210), 30)

    def test_rooms_have_separate_windows(self):
        other = FastRetryWindow(True, 30, 300, 900, clock=self.clock)
        self.assertTrue(self.retry.recording_ended())
        self.assertEqual(self.retry.next_delay(210), 30)
        self.assertEqual(other.next_delay(210), 210)
        self.clock.advance(75)
        self.assertTrue(other.recording_ended())
        self.assertEqual(other.next_delay(210), 30)

    def test_disabled_feature_preserves_legacy_scheduler(self):
        self.retry.configure(False)
        self.assertFalse(self.retry.recording_ended())
        self.assertEqual(self.retry.next_delay(210), 210)
        self.retry.configure(True)
        self.assertEqual(self.retry.next_delay(210), 210)

    def test_short_and_zero_normal_interval(self):
        self.retry.recording_ended()
        self.assertEqual(self.retry.next_delay(12), 12)
        self.assertEqual(self.retry.next_delay(0), 0)

    def test_settings_are_bounded_and_invalid_values_fall_back(self):
        self.retry.configure(True, 'invalid', '-200', '1000000')
        self.assertEqual(self.retry.interval_seconds, 30)
        self.assertEqual(self.retry.window_seconds, 60)
        self.assertEqual(self.retry.cooldown_seconds, 86400)
        self.retry.configure(True, '60', '600', '1800')
        self.assertEqual((self.retry.interval_seconds, self.retry.window_seconds,
                          self.retry.cooldown_seconds), (60, 600, 1800))

    def test_monotonic_window_not_affected_by_wall_clock(self):
        self.retry.recording_ended()
        self.clock.advance(120)
        self.assertEqual(self.retry.next_delay(210), 30)
        self.clock.advance(180)
        self.assertEqual(self.retry.next_delay(210), 210)


class RecorderWiringTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        source = (Path(__file__).resolve().parents[1] / "main.py").read_text(encoding="utf-8-sig")
        cls.tree = ast.parse(source)
        cls.functions = {
            node.name: node for node in cls.tree.body
            if isinstance(node, ast.FunctionDef)
        }

    def test_all_six_ffmpeg_recording_formats_supply_completion_hook(self):
        worker = self.functions["start_record"]
        calls = [
            node for node in ast.walk(worker)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "check_subprocess"
        ]
        self.assertEqual(len(calls), 6)
        for call in calls:
            self.assertEqual(
                [k.arg for k in call.keywords], ["on_natural_recording_end"]
            )

    def test_direct_flv_receives_completion_hook(self):
        worker = self.functions["start_record"]
        calls = [
            node for node in ast.walk(worker)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "direct_download_stream"
        ]
        self.assertEqual(len(calls), 1)
        self.assertEqual([k.arg for k in calls[0].keywords], ["on_natural_recording_end"])

    def test_callback_only_follows_natural_ffmpeg_exit(self):
        worker = self.functions["check_subprocess"]
        callbacks = [
            node for node in ast.walk(worker)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "on_natural_recording_end"
        ]
        self.assertEqual(len(callbacks), 1)
        callback = callbacks[0]
        self.assertTrue(
            any(isinstance(node, ast.Return) and node.lineno < callback.lineno
                for node in ast.walk(worker))
        )

    def test_main_keeps_legacy_one_shot_when_feature_disabled(self):
        worker = self.functions["start_record"]
        one_shot = [
            node for node in ast.walk(worker)
            if isinstance(node, ast.If)
            and isinstance(node.test, ast.Name)
            and node.test.id == "record_finished"
        ]
        self.assertEqual(len(one_shot), 1)
        self.assertTrue(
            any(isinstance(node, ast.Name) and node.id == "fast_retry"
                for node in ast.walk(worker))
        )


if __name__ == '__main__':
    unittest.main()

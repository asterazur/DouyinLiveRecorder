"""Bounded per-room fast polling after a recording ends.

Each monitoring worker owns its own instance.  The monotonic clock prevents
wall-clock adjustments from extending or shortening the window/cooldown.
"""

import math
import time


class FastRetryWindow:
    """One fixed fast-check window followed by a mandatory cooldown."""

    def __init__(self, enabled=False, interval_seconds=30, window_seconds=300,
                 cooldown_seconds=900, clock=None):
        self._clock = clock if clock is not None else time.monotonic
        self._active_until = None
        self._next_eligible_at = None
        self.configure(enabled, interval_seconds, window_seconds, cooldown_seconds)

    @staticmethod
    def _bounded_seconds(value, default, minimum, maximum):
        try:
            value = int(value)
        except (ValueError, TypeError, OverflowError):
            value = default
        return max(minimum, min(maximum, value))

    def configure(self, enabled, interval_seconds=30, window_seconds=300,
                  cooldown_seconds=900):
        # Disabling the feature cancels its active window and cooldown.
        if not enabled:
            self._active_until = None
            self._next_eligible_at = None
        self.enabled = bool(enabled)
        self.interval_seconds = self._bounded_seconds(interval_seconds, 30, 15, 300)
        self.window_seconds = self._bounded_seconds(window_seconds, 300, 60, 1800)
        self.cooldown_seconds = self._bounded_seconds(cooldown_seconds, 900, 300, 86400)

    def recording_ended(self):
        """Start a window for a natural completion/backend failure, if eligible.

        Do not call this for a room-disable or recorder-shutdown stop.  Repeat
        recording exits cannot extend the current window or bypass cooldown.
        """
        if not self.enabled:
            return False
        now = self._clock()
        if self._next_eligible_at is not None and now < self._next_eligible_at:
            return False
        self._active_until = now + self.window_seconds
        self._next_eligible_at = self._active_until + self.cooldown_seconds
        return True

    def window_active(self):
        return (
            self.enabled and self._active_until is not None
            and self._clock() < self._active_until
        )

    def next_delay(self, normal_delay):
        """Return an accelerated delay without exceeding the window boundary.

        A zero-delay normal configuration is never made slower.  A final check
        may be shorter than the fast interval at the exact end of the window.
        """
        if normal_delay <= 0 or not self.window_active():
            return normal_delay
        remaining = self._active_until - self._clock()
        if remaining <= 0:
            return normal_delay
        return min(normal_delay, self.interval_seconds, max(1, math.ceil(remaining)))

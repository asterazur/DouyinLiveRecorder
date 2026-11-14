# Per-room temporary fast retry (Stage B)

This feature belongs to the recorder core, so it works with the Python command
line, packaged Windows executable, and Docker independently of DLR_UI.
It is **disabled by default** to preserve Hmily's existing behaviour.

## Recorder config.ini ([录制设置])

| Option | Default | Supported range | Meaning |
| --- | --- | --- | --- |
| `录制结束后快速检测(是/否)` | `否` | `是` / `否` | Enable bounded fast checks after a recording ends |
| `快速检测间隔(秒)` | `30` | 15–300 | Check interval within the window |
| `快速检测窗口(秒)` | `300` | 60–1800 | Duration of a fast-check window |
| `快速检测冷却(秒)` | `900` | 300–86400 | Minimum rest after the window before another window can start |

The recorder adds missing keys to its config file when loading it. Invalid
numeric values fall back to defaults; out-of-range values are clamped.
For example, in a local test installation:

```ini
[录制设置]
录制结束后快速检测(是/否) = 是
快速检测间隔(秒) = 30
快速检测窗口(秒) = 300
快速检测冷却(秒) = 900
```

These settings are read as part of the recorder's normal configuration reload.
A room worker picks them up on its next monitoring attempt. Switching this
feature off cancels the active fast window and cooldown for that worker.
Each room runs its own timer; one broadcaster never accelerates another.

## Behaviour

1. No fast window starts merely because a room is offline. Normal offline
   monitoring continues at the configured `循环时间(秒)` interval.
2. After an actual recording **naturally finishes** or its backend exits with
   an error, the room starts its own fixed 300-second fast window if eligible.
   This includes all six FFmpeg recording formats and the direct-FLV path,
   including FFmpeg exit code 0. An unsuccessful probe that never started a
   recording does not open a window.
3. While the window is active, room checks use the smaller of the normal
   interval, the fast interval, and the time remaining before the window ends.
   The last interval can therefore be shorter than 30 seconds.
4. Repeated recording exits **do not extend** an existing fast window.
   Once it ends, a 900-second cooldown applies. A new window may begin only
   after this cooldown and a new natural recording stop.
5. Deliberate recorder shutdown, room disable or disk-limit cancellation
   **does not start a fast window**. Existing interruptible waits remain in
   effect. When the feature is enabled, the bounded scheduler replaces the
   legacy one-shot 30-second post-recording check; it cannot be bypassed by
   a rapid series of FFmpeg failures.
6. Existing high global error-count backoff takes precedence over fast
   polling to avoid increasing requests when the backend is overloaded.
7. When this feature is **disabled**, the existing one-shot 30-second
   post-recording check (Stage A) remains unchanged.

All window/cooldown deadlines use `time.monotonic()` so wall-clock changes
cannot extend the window or defeat the cooldown. Timers are in-memory and
reset when the room worker or recorder restarts; there is no cross-run
persistence.

## Diagnostics and testing

When a fast window begins, the recorder's log includes `Fast retry started
for room ...` with the configured values. Existing `room_waiting` runtime
events continue reporting the actual `retry_after` and `next_check`
used by DLR_UI; no changes to Hmily PR #1458 are required for Stage B.

Run:

```shell
python -m unittest discover -s tests -p 'test_fast_retry.py' -v
python -m unittest discover -s tests -p 'test_post_recording_retry.py' -v
python -m unittest discover -s tests -p 'test_shutdown_control.py' -v
```

These tests cover isolated room clocks, bounded windows, cooldown, backend
hook wiring and legacy mode. They do **not** substitute for running the updated
recorder in a disposable Windows test installation to check real FFmpeg exit,
DLR_UI event timing, process control and output-file safety.

The separate DLR_UI configuration controls and Alpha packaging defaults
must be implemented and reviewed before final release. Do not put Stage B
changes into the currently open upstream runtime-events PR #1458.

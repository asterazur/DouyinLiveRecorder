# Graceful recorder shutdown (experimental: e002)

This documents the prototype for a public, installation-scoped shutdown API.
It does not require DLR_UI. All mechanisms request orderly shutdown; none
performs process termination.

## Terminal

For a recorder already running in a terminal, enter `q` followed by Enter.
`Ctrl+C` and `SIGTERM` also request the same orderly shutdown (where
supported by the OS). During first-run interactive URL entry, complete the
URL prompt first.

## Other applications and scripts

The process you wish to stop must be running the updated recorder code.
From that same installation directory, run:

```sh
python main.py --stop --pid 12345
```

For a PyInstaller build, run:

```powershell
.\DouyinLiveRecorder.exe --stop --pid 12345
```

Replace `12345` with the PID of the **specific recorder runtime**, not a
system-wide process name. A successful command confirms that the shutdown
request was **accepted**, not that all recordings have finished. Consumers
should then wait for the `runtime_stopped` event and/or process exit.

The command searches only this installation's `logs` directory; it cannot
control a different installation just because it uses the same executable
name. If the descriptor is missing, stale or mismatched, the command fails
rather than killing anything.

## Local integration protocol (version 1)

While running, DLR creates
`logs/runtime_control.<pid>.json` in its own installation. The descriptor
contains `protocol_version`, `pid`, `instance_id`, a random `token`,
and a local TCP `port`.

- Connect to `127.0.0.1:<port>` only.
- Send one newline-terminated JSON message containing:
  `{"protocol_version":1,"command":"shutdown","pid":12345,"instance_id":"...","token":"..."}`.
- Receive a JSON line with `status: "accepted"`, the matching PID and
  instance ID. A rejection or connection failure must never be treated as
  authorization to terminate another process.
- Descriptors are scoped to the recorder installation. On POSIX systems
  their temporary files are created with owner-only permissions. On Windows
  access depends on the directory's NTFS ACL; installations should be
  protected from untrusted local users.

External apps should independently verify the target recorder executable
path before using a descriptor; the token only authenticates the request,
not the executable on disk. The server binds only to localhost and removes
its matching descriptor after an orderly exit.

## Recorder lifecycle

The shutdown request sets a shared stop event and prevents new room worker
launches. Active worker threads are allowed to stop their own FFmpeg
processes via the existing `q`-to-stdin path, wait for them and finish
processing. DLR writes `runtime_stopping` and later `runtime_stopped`
to `logs/runtime_events.jsonl` using runtime events schema version 2.1.
The final event includes `runtime_pid`, `reason` and `status`.

The recorder does **not** convert a slow graceful shutdown into a kill.
Active network operations and output conversions may extend the delay.
A caller that must provide an emergency kill should implement that as a
separate, explicit decision with appropriate process-path verification.

## Local tests

```sh
python -m unittest discover -s tests -p 'test_shutdown_control.py'
```

Before proposing this upstream, test the built executable on Windows and
Linux with no rooms, monitoring rooms, FFmpeg recording, a stalled backend,
and concurrent installations. The integration should never stop a recorder
or FFmpeg process belonging to another installation.

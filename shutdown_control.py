"""Per-instance, local-only graceful shutdown control for DouyinLiveRecorder.

The recorder publishes a short-lived control descriptor in its own logs directory.
An external client supplies the per-instance token to a loopback TCP listener.
No process is ever killed by this module.
"""
import argparse
import hmac
import json
import os
import secrets
import socket
import tempfile
import threading

PROTOCOL_VERSION = 1
MAX_MESSAGE_BYTES = 4096


def descriptor_path(application_directory, pid):
    return os.path.join(
        application_directory, "logs", "runtime_control.%d.json" % int(pid)
    )


def _receive_line(connection):
    chunks = bytearray()
    while len(chunks) < MAX_MESSAGE_BYTES:
        part = connection.recv(1)
        if not part:
            break
        if part == b"\n":
            return json.loads(chunks.decode("utf-8"))
        chunks.extend(part)
    raise ValueError("Invalid or oversized control message")


def _send_json(connection, data):
    connection.sendall(
        (json.dumps(data, separators=(",", ":")) + "\n").encode("utf-8")
    )


class ShutdownControlServer:
    def __init__(self, application_directory, request_shutdown):
        self.pid = os.getpid()
        self.path = descriptor_path(application_directory, self.pid)
        self.instance_id = secrets.token_hex(16)
        self.token = secrets.token_hex(32)
        self.request_shutdown = request_shutdown
        self._closed = threading.Event()
        self._socket = None
        self._thread = None

    def start(self):
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            listener.bind(("127.0.0.1", 0))
            listener.listen(4)
            listener.settimeout(0.5)
            self._socket = listener
            descriptor = {
                "protocol_version": PROTOCOL_VERSION,
                "pid": self.pid,
                "instance_id": self.instance_id,
                "port": listener.getsockname()[1],
                "token": self.token,
            }
            temporary = None
            try:
                fd, temporary = tempfile.mkstemp(
                    prefix=".runtime_control.", suffix=".tmp",
                    dir=os.path.dirname(self.path)
                )
                with os.fdopen(fd, "w", encoding="utf-8") as output:
                    json.dump(descriptor, output)
                    output.write("\n")
                os.replace(temporary, self.path)
            finally:
                if temporary and os.path.exists(temporary):
                    os.unlink(temporary)
            self._thread = threading.Thread(
                target=self._serve, name="DLRShutdownControl", daemon=True
            )
            self._thread.start()
        except Exception:
            listener.close()
            self._socket = None
            raise

    def _serve(self):
        while not self._closed.is_set():
            try:
                connection, _ = self._socket.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            with connection:
                connection.settimeout(2.0)
                try:
                    request = _receive_line(connection)
                    authenticated = (
                        isinstance(request, dict)
                        and request.get("protocol_version") == PROTOCOL_VERSION
                        and request.get("pid") == self.pid
                        and request.get("instance_id") == self.instance_id
                        and isinstance(request.get("token"), str)
                        and hmac.compare_digest(request["token"], self.token)
                    )
                    if not authenticated or request.get("command") != "shutdown":
                        _send_json(connection, {"status": "rejected"})
                        continue
                    self.request_shutdown("external_request")
                    _send_json(connection, {
                        "status": "accepted",
                        "pid": self.pid,
                        "instance_id": self.instance_id,
                    })
                except (OSError, ValueError, TypeError, UnicodeError):
                    pass

    def close(self):
        self._closed.set()
        if self._socket is not None:
            self._socket.close()
        if self._thread is not None:
            self._thread.join(timeout=2.0)
        try:
            with open(self.path, "r", encoding="utf-8") as handle:
                state = json.load(handle)
            if state.get("instance_id") == self.instance_id:
                os.unlink(self.path)
        except (OSError, ValueError, TypeError):
            pass


def request_shutdown(application_directory, pid):
    """Ask ONE instance in this installation to stop, never kill it."""
    path = descriptor_path(application_directory, pid)
    with open(path, "r", encoding="utf-8") as handle:
        descriptor = json.load(handle)
    if (
        not isinstance(descriptor, dict)
        or descriptor.get("protocol_version") != PROTOCOL_VERSION
        or type(descriptor.get("pid")) is not int
        or descriptor["pid"] != int(pid)
        or not isinstance(descriptor.get("instance_id"), str)
        or not isinstance(descriptor.get("token"), str)
        or type(descriptor.get("port")) is not int
        or not (1 <= descriptor["port"] <= 65535)
    ):
        raise ValueError("Invalid shutdown control descriptor")

    request = {
        "protocol_version": PROTOCOL_VERSION,
        "command": "shutdown",
        "pid": int(pid),
        "instance_id": descriptor["instance_id"],
        "token": descriptor["token"],
    }
    with socket.create_connection(("127.0.0.1", descriptor["port"]), timeout=3.0) as connection:
        connection.settimeout(3.0)
        _send_json(connection, request)
        response = _receive_line(connection)
    if (
        not isinstance(response, dict)
        or response.get("status") != "accepted"
        or response.get("pid") != int(pid)
        or response.get("instance_id") != descriptor["instance_id"]
    ):
        raise RuntimeError("Shutdown request rejected by recorder")
    return response


def shutdown_cli(arguments, application_directory):
    parser = argparse.ArgumentParser(
        description="Request graceful shutdown of a DLR instance in this installation"
    )
    parser.add_argument("--stop", action="store_true", required=True)
    parser.add_argument("--pid", type=int, required=True)
    options = parser.parse_args(arguments)
    if options.pid <= 0:
        parser.error("--pid must be positive")
    try:
        request_shutdown(application_directory, options.pid)
    except (OSError, ValueError, RuntimeError) as error:
        print("DLR shutdown request failed: %s" % error)
        return 1
    print("DLR shutdown request accepted for PID %d" % options.pid)
    return 0

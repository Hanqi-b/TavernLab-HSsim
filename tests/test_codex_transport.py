import json
import os
import queue
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

import fireplace.codex_transport as codex_transport_module
from fireplace.codex_transport import CodexTransport, CodexTransportError


class _ReadStream:
    def __init__(self):
        self._lines = queue.Queue()

    def put(self, value):
        self._lines.put(value)

    def readline(self, size=-1):
        value = self._lines.get()
        if value is None:
            return ""
        if size >= 0 and len(value) > size:
            # The transport drains a long line with repeated bounded reads.
            result, remainder = value[:size], value[size:]
            self._lines.put(remainder)
            return result
        return value


class _WriteStream:
    def __init__(self, callback):
        self.messages = []
        self._callback = callback
        self.closed = False

    def write(self, value):
        self.messages.append(value)
        self._callback(json.loads(value))
        return len(value)

    def flush(self):
        return None

    def close(self):
        self.closed = True


class _Process:
    def __init__(self):
        self.stdout = _ReadStream()
        self.stderr = _ReadStream()
        self._returncode = None
        self.stdin = _WriteStream(self._on_message)
        self._next_turn = 0

    def poll(self):
        return self._returncode

    def terminate(self):
        self._returncode = -15
        self.stdout.put(None)
        self.stderr.put(None)

    def kill(self):
        self._returncode = -9
        self.stdout.put(None)
        self.stderr.put(None)

    def wait(self, timeout=None):
        self._returncode = self._returncode if self._returncode is not None else 0
        return self._returncode

    def _emit(self, value):
        self.stdout.put(json.dumps(value) + "\n")

    def _on_message(self, message):
        method = message.get("method")
        request_id = message.get("id")
        if method == "initialize":
            self._emit({"jsonrpc": "2.0", "id": request_id, "result": {}})
        elif method == "thread/start":
            self._emit(
                {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "result": {"thread": {"id": "thread-1"}},
                }
            )
        elif method == "turn/start":
            self._next_turn += 1
            turn_id = "turn-%s" % self._next_turn
            self._emit(
                {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "result": {"turn": {"id": turn_id}},
                }
            )


def test_jsonl_requests_and_notifications_use_one_child(monkeypatch, tmp_path):
    config_home = tmp_path / "codex"
    config_home.mkdir()
    (config_home / "config.toml").write_text(
        '[mcp_servers."secret.name"]\ncommand = "do-not-print"\n\n'
        '[profiles.card.mcp_servers.profile-server]\ncommand = "also-do-not-print"\n\n'
        '[[profiles_with_tables]]\n'
        '[profiles_with_tables.mcp_servers.array-server]\n'
        'command = "still-do-not-print"\n',
        encoding="utf-8",
    )
    monkeypatch.setenv("CODEX_HOME", str(config_home))
    processes = []

    def factory(command, **kwargs):
        assert kwargs["shell"] is False
        assert "app-server" in command
        assert "-c" in command
        assert any("features.shell_tool=false" == item for item in command)
        assert any("tools.view_image=false" == item for item in command)
        assert any("mcp_servers.\"secret.name\".enabled=false" == item for item in command)
        assert any("mcp_servers.profile-server.enabled=false" == item for item in command)
        assert any("mcp_servers.array-server.enabled=false" == item for item in command)
        process = _Process()
        processes.append(process)
        return process

    transport = CodexTransport(binary="codex", process_factory=factory, cwd=tmp_path / "isolated")
    assert transport.request("initialize", {}, timeout=1) == {}
    assert transport.request("thread/start", {}, timeout=1)["thread"]["id"] == "thread-1"
    transport.close()
    assert len(processes) == 1
    assert processes[0].stdin.closed


def test_command_mcp_scan_uses_effective_child_codex_home(monkeypatch, tmp_path):
    parent_home = tmp_path / "parent"
    child_home = tmp_path / "child"
    parent_home.mkdir()
    child_home.mkdir()
    (parent_home / "config.toml").write_text(
        '[mcp_servers.parent-only]\ncommand = "parent"\n', encoding="utf-8"
    )
    (child_home / "config.toml").write_text(
        '[mcp_servers.child-only]\ncommand = "child"\n', encoding="utf-8"
    )
    monkeypatch.setenv("CODEX_HOME", str(parent_home))
    command = codex_transport_module._build_command(
        "codex", (), env={"CODEX_HOME": str(child_home)}
    )
    assert "mcp_servers.child-only.enabled=false" in command
    assert "mcp_servers.parent-only.enabled=false" not in command


def test_server_requests_are_denied_without_exposing_diagnostics(tmp_path):
    process = _Process()

    def factory(command, **kwargs):
        process._emit(
            {
                "jsonrpc": "2.0",
                "id": "server-request",
                "method": "item/commandExecution/requestApproval",
                "params": {"secret": "diagnostic-token"},
            }
        )
        return process

    transport = CodexTransport(binary="codex", process_factory=factory, cwd=tmp_path)
    assert transport.request("initialize", {}, timeout=1) == {}
    written = "".join(process.stdin.messages)
    assert "diagnostic-token" not in written
    assert '"id":"server-request"' in written
    assert '"error"' in written
    transport.close()


def test_eof_wakes_waiter_and_reset_allows_a_new_child(tmp_path):
    processes = []

    def factory(command, **kwargs):
        process = _Process()
        processes.append(process)
        return process

    transport = CodexTransport(binary="codex", process_factory=factory, cwd=tmp_path)
    transport.start()
    processes[0].stdout.put(None)
    with pytest.raises(CodexTransportError, match="exited unexpectedly"):
        transport.wait_for_notification(timeout=1)
    transport.reset()
    transport.start()
    assert len(processes) == 2
    transport.close()


def test_old_reader_eof_cannot_enter_restarted_session_queue(tmp_path):
    processes = []

    class StickyProcess(_Process):
        def terminate(self):
            # Keep the old reader blocked until the test releases it after a
            # replacement child has started.
            self._returncode = -15

        def kill(self):
            self._returncode = -9

    def factory(command, **kwargs):
        process = StickyProcess()
        processes.append(process)
        return process

    transport = CodexTransport(binary="codex", process_factory=factory, cwd=tmp_path)
    transport.start()
    old_process = processes[0]
    transport.reset()
    transport.start()
    new_process = processes[1]

    old_process.stdout.put(None)
    new_process.stdout.put(
        json.dumps({"jsonrpc": "2.0", "method": "turn/started", "params": {}})
        + "\n"
    )
    event = transport.wait_for_notification(timeout=1)
    assert event["method"] == "turn/started"
    transport.close()


def test_reset_between_select_and_write_cannot_reuse_fd_for_new_child(
    monkeypatch, tmp_path
):
    processes = []
    select_ready = threading.Event()
    release_select = threading.Event()
    script = (
        "import json,sys\n"
        "for line in sys.stdin:\n"
        " print(json.dumps({'method':'received','params':json.loads(line)}), flush=True)\n"
    )

    def factory(command, **kwargs):
        process = subprocess.Popen([sys.executable, "-u", "-c", script], **kwargs)
        processes.append(process)
        return process

    original_select = codex_transport_module.select.select

    def gated_select(readable, writable, exceptional, timeout):
        result = original_select(readable, writable, exceptional, timeout)
        if writable and result[1] and not select_ready.is_set():
            select_ready.set()
            assert release_select.wait(2.0)
        return result

    monkeypatch.setattr(codex_transport_module.select, "select", gated_select)
    transport = CodexTransport(binary="codex", process_factory=factory, cwd=tmp_path)
    errors = []

    def old_writer():
        try:
            transport.send_notification("old-generation", {"secret": "old-state"})
        except BaseException as exc:
            errors.append(exc)

    writer = threading.Thread(target=old_writer, name="old-writer")
    writer.start()
    assert select_ready.wait(1.0)
    old_fd = processes[0].stdin.fileno()
    transport.reset()
    transport.start()
    new_fd = processes[1].stdin.fileno()
    assert old_fd == new_fd
    release_select.set()
    writer.join(timeout=1.0)
    assert not writer.is_alive()
    assert errors
    with pytest.raises(CodexTransportError, match="Timed out"):
        transport.wait_for_notification(timeout=0.4)
    transport.close()


def test_wait_timeout_and_close_do_not_leave_reader_blocked(tmp_path):
    process = _Process()

    def factory(command, **kwargs):
        return process

    transport = CodexTransport(binary="codex", process_factory=factory, cwd=tmp_path)
    transport.start()
    with pytest.raises(CodexTransportError, match="Timed out"):
        transport.wait_for_notification(timeout=0.02)
    waiter_error = []

    def wait_forever():
        try:
            transport.wait_for_notification()
        except CodexTransportError as exc:
            waiter_error.append(str(exc))

    thread = threading.Thread(target=wait_forever)
    thread.start()
    time.sleep(0.03)
    transport.close()
    thread.join(timeout=1)
    assert not thread.is_alive()
    assert waiter_error


def test_real_stalled_stdin_write_has_deadline_and_reset_reopens(tmp_path):
    processes = []

    def factory(command, **kwargs):
        # A local child that never reads stdin fills the OS pipe.  This uses
        # the actual subprocess pipes, rather than a fake write method, so a
        # request must be bounded by the transport deadline.
        process = subprocess.Popen(
            [sys.executable, "-c", "import time; time.sleep(30)"],
            **kwargs,
        )
        processes.append(process)
        return process

    transport = CodexTransport(binary="codex", process_factory=factory, cwd=tmp_path)
    started = time.monotonic()
    with pytest.raises(CodexTransportError, match="Timed out"):
        transport.request("blocked", {"blob": "x" * (4 * 1024 * 1024)}, timeout=0.08)
    assert time.monotonic() - started < 1.0
    assert processes[0].poll() is None

    transport.reset()
    assert processes[0].poll() is not None
    transport.start()
    assert len(processes) == 2
    transport.close()
    assert processes[1].poll() is not None


def test_close_interrupts_hung_real_stdin_write_and_terminates_child(tmp_path):
    processes = []
    child_created = threading.Event()

    def factory(command, **kwargs):
        process = subprocess.Popen(
            [sys.executable, "-c", "import time; time.sleep(30)"],
            **kwargs,
        )
        processes.append(process)
        child_created.set()
        return process

    transport = CodexTransport(binary="codex", process_factory=factory, cwd=tmp_path)
    errors = []

    def request_forever():
        try:
            transport.request(
                "blocked",
                {"blob": "x" * (4 * 1024 * 1024)},
                timeout=None,
            )
        except BaseException as exc:  # the transport must wake this caller
            errors.append(exc)

    worker = threading.Thread(target=request_forever)
    worker.start()
    assert child_created.wait(1.0)
    time.sleep(0.05)
    started = time.monotonic()
    transport.close()
    close_elapsed = time.monotonic() - started
    worker.join(timeout=1.0)
    assert close_elapsed < 1.0
    assert not worker.is_alive()
    assert errors
    assert processes[0].poll() is not None


def test_close_kills_inherited_output_pipe_descendant_without_waiting(tmp_path):
    if not hasattr(os, "fork"):
        pytest.skip("requires POSIX process groups")
    pid_file = tmp_path / "grandchild.pid"
    fake_binary = tmp_path / "codex-grandchild"
    fake_binary.write_text(
        "#!%s\n"
        "import os, time\n"
        "pid = os.fork()\n"
        "if pid == 0:\n"
        "    with open(os.environ['TAVERNLAB_TEST_PID_FILE'], 'w') as stream:\n"
        "        stream.write(str(os.getpid()))\n"
        "    time.sleep(30)\n"
        "    os._exit(0)\n"
        "time.sleep(0.1)\n"
        "os._exit(0)\n" % sys.executable,
        encoding="utf-8",
    )
    fake_binary.chmod(0o755)
    transport = CodexTransport(
        binary=fake_binary,
        cwd=tmp_path,
        env={"TAVERNLAB_TEST_PID_FILE": str(pid_file)},
    )
    transport.start()
    deadline = time.monotonic() + 1.0
    while not pid_file.exists() and time.monotonic() < deadline:
        time.sleep(0.01)
    assert pid_file.exists()
    child_pid = int(pid_file.read_text(encoding="utf-8"))
    process = transport.process
    assert process is not None
    deadline = time.monotonic() + 1.0
    while process.poll() is None and time.monotonic() < deadline:
        time.sleep(0.01)

    started = time.monotonic()
    transport.close()
    assert time.monotonic() - started < 1.0
    assert process.poll() is not None

    # A killed descendant may briefly remain as a zombie while init reaps it,
    # but it must not stay runnable or sleeping with the inherited pipe open.
    deadline = time.monotonic() + 1.0
    while time.monotonic() < deadline:
        try:
            state = Path("/proc") / str(child_pid) / "stat"
            fields = state.read_text(encoding="utf-8").split()
            if len(fields) > 2 and fields[2] == "Z":
                break
        except (FileNotFoundError, ProcessLookupError):
            # procfs can report ESRCH if the descendant is reaped during
            # the read. That also confirms successful process cleanup.
            break
        time.sleep(0.01)
    else:
        pytest.fail("inherited output-pipe descendant survived transport.close()")

from pathlib import Path

import us_stock_signal.runtime_lock as runtime_lock_module
from us_stock_signal.runtime_lock import runtime_lock


def test_runtime_lock_blocks_second_holder(tmp_path):
    lock_path = tmp_path / "runtime.lock"

    with runtime_lock(lock_path) as first:
        with runtime_lock(lock_path) as second:
            assert first is True
            assert second is False

    assert not lock_path.exists()


def test_runtime_lock_creates_parent_directory(tmp_path):
    lock_path = tmp_path / "nested" / "runtime.lock"

    with runtime_lock(lock_path) as acquired:
        assert acquired is True
        assert Path(lock_path).exists()


def test_runtime_lock_retries_transient_cleanup_permission_error(monkeypatch, tmp_path):
    lock_path = tmp_path / "runtime.lock"
    original_unlink = Path.unlink
    attempts = {"count": 0}

    def flaky_unlink(path, *args, **kwargs):
        if path == lock_path and attempts["count"] == 0:
            attempts["count"] += 1
            raise PermissionError("transient lock")
        return original_unlink(path, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", flaky_unlink)
    monkeypatch.setattr(runtime_lock_module.time, "sleep", lambda _: None)

    with runtime_lock(lock_path) as acquired:
        assert acquired is True

    assert attempts["count"] == 1
    assert not lock_path.exists()


def test_runtime_lock_ignores_persistent_cleanup_permission_error(monkeypatch):
    class LockedPath:
        def __init__(self):
            self.attempts = 0

        def unlink(self):
            self.attempts += 1
            raise PermissionError("sandbox denied delete")

    locked_path = LockedPath()
    monkeypatch.setattr(runtime_lock_module.time, "sleep", lambda _: None)

    runtime_lock_module._unlink_with_retry(locked_path, attempts=2, delay_seconds=0)

    assert locked_path.attempts == 2


def test_runtime_lock_allows_stale_lock_when_pid_is_gone(monkeypatch, tmp_path):
    lock_path = tmp_path / "runtime.lock"
    lock_path.write_text("999999", encoding="ascii")
    monkeypatch.setattr(runtime_lock_module, "_process_exists", lambda pid: False)

    with runtime_lock(lock_path) as acquired:
        assert acquired is True

    assert lock_path.exists()


def test_runtime_lock_blocks_existing_lock_when_pid_is_alive(monkeypatch, tmp_path):
    lock_path = tmp_path / "runtime.lock"
    lock_path.write_text("12345", encoding="ascii")
    monkeypatch.setattr(runtime_lock_module, "_process_exists", lambda pid: True)

    with runtime_lock(lock_path) as acquired:
        assert acquired is False


def test_windows_process_exists_requires_still_active_exit_code():
    closed = []

    class FakeKernel32:
        def OpenProcess(self, access, inherit, pid):
            return 100

        def GetExitCodeProcess(self, handle, code_pointer):
            code_pointer._obj.value = 0
            return 1

        def CloseHandle(self, handle):
            closed.append(handle)

    assert runtime_lock_module._windows_process_exists(12345, FakeKernel32()) is False
    assert closed == [100]


def test_windows_process_exists_accepts_still_active_exit_code():
    class FakeKernel32:
        def OpenProcess(self, access, inherit, pid):
            return 100

        def GetExitCodeProcess(self, handle, code_pointer):
            code_pointer._obj.value = 259
            return 1

        def CloseHandle(self, handle):
            pass

    assert runtime_lock_module._windows_process_exists(12345, FakeKernel32()) is True

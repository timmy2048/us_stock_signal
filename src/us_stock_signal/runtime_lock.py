from __future__ import annotations

import ctypes
import os
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator


@contextmanager
def runtime_lock(lock_path: str | Path) -> Iterator[bool]:
    path = Path(lock_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    file_descriptor: int | None = None
    acquired = False
    try:
        file_descriptor = os.open(str(path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        os.write(file_descriptor, str(os.getpid()).encode("ascii"))
        acquired = True
        yield True
    except FileExistsError:
        yield _existing_lock_is_stale(path)
    finally:
        if file_descriptor is not None:
            os.close(file_descriptor)
        if acquired:
            _unlink_with_retry(path)


def _unlink_with_retry(path: Path, attempts: int = 5, delay_seconds: float = 0.05) -> None:
    for attempt in range(attempts):
        try:
            path.unlink()
            return
        except FileNotFoundError:
            return
        except PermissionError:
            if attempt == attempts - 1:
                return
            time.sleep(delay_seconds)


def _existing_lock_is_stale(path: Path) -> bool:
    try:
        raw_pid = path.read_text(encoding="ascii").strip()
        pid = int(raw_pid)
    except (OSError, ValueError):
        return False
    return not _process_exists(pid)


def _process_exists(pid: int) -> bool:
    if pid <= 0:
        return False
    if os.name == "nt":
        return _windows_process_exists(pid)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _windows_process_exists(pid: int, kernel32=None) -> bool:
    kernel32 = kernel32 or ctypes.WinDLL("kernel32", use_last_error=True)
    process_query_limited_information = 0x1000
    handle = kernel32.OpenProcess(process_query_limited_information, False, pid)
    if not handle:
        return False
    try:
        still_active = 259
        exit_code = ctypes.c_uint32()
        if kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code)):
            return exit_code.value == still_active
        return True
    finally:
        kernel32.CloseHandle(handle)

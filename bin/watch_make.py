#!/usr/bin/env python3
from __future__ import annotations

import argparse
import errno
import os
import signal
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

# Workspace-relative files/directories to skip while watching.
DEFAULT_EXCLUDED_PATHS = {"latex.out", ".git"}
EXCLUDED_PATHS = set(DEFAULT_EXCLUDED_PATHS)
DEBOUNCE_SECONDS = 0.25


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Watch workspace files and rerun make on changes."
    )
    parser.add_argument(
        "--exclude",
        action="append",
        default=[],
        help=(
            "Workspace-relative path(s) to exclude from watching. "
            "Can be passed multiple times or as a comma-separated list."
        ),
    )
    return parser.parse_args()


def _parse_exclusions(raw_exclusions: list[str]) -> set[str]:
    if not raw_exclusions:
        return set(DEFAULT_EXCLUDED_PATHS)

    parsed: set[str] = set()
    for value in raw_exclusions:
        for item in value.split(","):
            normalized = item.strip().strip("/")
            if normalized:
                parsed.add(normalized)

    return parsed or set(DEFAULT_EXCLUDED_PATHS)


def _is_excluded(path: Path, root: Path) -> bool:
    try:
        relative_path = path.relative_to(root)
    except ValueError:
        return False

    for excluded in EXCLUDED_PATHS:
        excluded_path = Path(excluded)
        try:
            relative_path.relative_to(excluded_path)
            return True
        except ValueError:
            continue

    return False


def _collect_paths(root: Path) -> tuple[list[Path], list[Path]]:
    files: list[Path] = []
    dirs: list[Path] = [root]

    for candidate in root.rglob("*"):
        if _is_excluded(candidate, root):
            continue
        if candidate.is_dir():
            dirs.append(candidate)
        elif candidate.is_file():
            files.append(candidate)

    # De-duplicate and sort for deterministic behavior.
    files = sorted(set(files))
    dirs = sorted(set(dirs))
    return files, dirs


def _open_fd(path: Path) -> int | None:
    try:
        return os.open(path, os.O_RDONLY)
    except OSError:
        return None


def _build_watchers(kq: select.kqueue, root: Path):
    for fd in list(fd_to_path):
        try:
            os.close(fd)
        except OSError:
            pass
        fd_to_path.pop(fd, None)

    files, dirs = _collect_paths(root)

    registrations: list[select.kevent] = []
    for path in files + dirs:
        fd = _open_fd(path)
        if fd is None:
            continue
        fd_to_path[fd] = path
        registrations.append(
            select.kevent(
                fd,
                filter=select.KQ_FILTER_VNODE,
                flags=select.KQ_EV_ADD | select.KQ_EV_ENABLE | select.KQ_EV_CLEAR,
                fflags=(
                    select.KQ_NOTE_WRITE
                    | select.KQ_NOTE_DELETE
                    | select.KQ_NOTE_EXTEND
                    | select.KQ_NOTE_ATTRIB
                    | select.KQ_NOTE_RENAME
                    | select.KQ_NOTE_REVOKE
                ),
            )
        )

    if registrations:
        kq.control(registrations, 0, 0)


def _event_causes(events: list[select.kevent], root: Path) -> list[str]:
    causes: set[str] = set()
    for event in events:
        path = fd_to_path.get(event.ident)
        if path is None:
            continue
        try:
            relative = path.relative_to(root)
            causes.add(str(relative))
        except ValueError:
            causes.add(str(path))

    if not causes:
        return ["(unknown path)"]
    return sorted(causes)


def _run_make(root: Path, build_count: int, causes: list[str] | None = None) -> int:
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    cause_text = ""
    if causes:
        cause_text = f" | cause: {', '.join(causes)}"
    print(
        f"\n[watch_make] remaking #{build_count} at {timestamp}{cause_text} -> running make",
        flush=True,
    )
    proc = subprocess.run(["make"], cwd=root)
    if proc.returncode == 0:
        print("[watch_make] make succeeded", flush=True)
    else:
        print(f"[watch_make] make failed (exit {proc.returncode})", flush=True)
    return proc.returncode


def _drain_events(kq: select.kqueue) -> list[select.kevent]:
    drained: list[select.kevent] = []
    while True:
        events = kq.control(None, 64, 0)
        if not events:
            return drained
        drained.extend(events)


def _handle_signal(signum, _frame):
    raise KeyboardInterrupt(signum)


try:
    import select
except ImportError as exc:
    print(f"[watch_make] select module unavailable: {exc}", file=sys.stderr)
    sys.exit(1)

if not hasattr(select, "kqueue"):
    print("[watch_make] kqueue is not available on this Python build/OS.", file=sys.stderr)
    sys.exit(1)

args = _parse_args()
EXCLUDED_PATHS = _parse_exclusions(args.exclude)

root = Path(__file__).resolve().parent.parent
fd_to_path: dict[int, Path] = {}

signal.signal(signal.SIGINT, _handle_signal)
signal.signal(signal.SIGTERM, _handle_signal)

print("[watch_make] watching for changes using kqueue (no external dependencies)", flush=True)
print(f"[watch_make] workspace: {root}", flush=True)
print(f"[watch_make] exclusions: {', '.join(sorted(EXCLUDED_PATHS))}", flush=True)

kq = select.kqueue()

try:
    _build_watchers(kq, root)
    build_count = 1
    _run_make(root, build_count, ["(initial run)"])

    while True:
        events = kq.control(None, 64, None)
        if not events:
            continue

        # Coalesce event bursts from a single save into one make call.
        time.sleep(DEBOUNCE_SECONDS)
        all_events = events + _drain_events(kq)
        causes = _event_causes(all_events, root)

        _build_watchers(kq, root)
        build_count += 1
        _run_make(root, build_count, causes)

except KeyboardInterrupt:
    print("\n[watch_make] stopping", flush=True)
finally:
    try:
        kq.close()
    except OSError:
        pass
    for fd in list(fd_to_path):
        try:
            os.close(fd)
        except OSError as exc:
            if exc.errno != errno.EBADF:
                raise

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime
import os
from pathlib import Path
import re
import sys
from typing import Callable, Iterator, Optional, Sequence, TextIO, TypeVar


T = TypeVar("T")


class TeeStream:
    def __init__(self, stream: TextIO, log_file: TextIO):
        self._stream = stream
        self._log_file = log_file

    def write(self, text: str) -> int:
        self._stream.write(text)
        self._log_file.write(text)
        return len(text)

    def flush(self) -> None:
        self._stream.flush()
        self._log_file.flush()

    def isatty(self) -> bool:
        return False

    @property
    def encoding(self) -> Optional[str]:
        return getattr(self._stream, "encoding", None)


def _safe_part(value: object) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_.=-]+", "_", str(value or "").strip())
    return cleaned.strip("._") or "unknown"


def _arg_value(argv: Sequence[str], name: str, default: str = "") -> str:
    prefix = f"{name}="
    for index, arg in enumerate(argv):
        if arg == name and index + 1 < len(argv):
            return argv[index + 1]
        if arg.startswith(prefix):
            return arg[len(prefix) :]
    return default


def log_dir_for(root: Path) -> Path:
    configured = os.environ.get("EVERMEMBENCH_LOG_DIR")
    return Path(configured).expanduser() if configured else root / "log"


def build_log_path(root: Path, stage: str, argv: Sequence[str]) -> Path:
    topic = _arg_value(argv, "--topic", "all")
    run_id = os.environ.get("EVERMEMBENCH_RUN_ID") or datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"{_safe_part(stage)}_topic{_safe_part(topic)}_{_safe_part(run_id)}_pid{os.getpid()}.log"
    return log_dir_for(root) / filename


@contextmanager
def tee_stdio(log_path: Path) -> Iterator[None]:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    original_stdout = sys.stdout
    original_stderr = sys.stderr
    with log_path.open("a", encoding="utf-8", buffering=1) as log_file:
        sys.stdout = TeeStream(original_stdout, log_file)  # type: ignore[assignment]
        sys.stderr = TeeStream(original_stderr, log_file)  # type: ignore[assignment]
        try:
            print(f"== EverMemBench log: {log_path} ==", flush=True)
            yield
        finally:
            sys.stdout.flush()
            sys.stderr.flush()
            sys.stdout = original_stdout
            sys.stderr = original_stderr


def run_with_stage_log(root: Path, stage: str, argv: Sequence[str], fn: Callable[[], T]) -> T:
    if any(arg in {"-h", "--help"} for arg in argv):
        return fn()
    log_path = build_log_path(root, stage, argv)
    with tee_stdio(log_path):
        return fn()

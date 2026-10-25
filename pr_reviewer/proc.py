"""외부 프로세스 실행 계약 (ADR-004). gh/claude 호출 함수는 Runner를 주입받는다."""

import subprocess
from typing import Callable

Runner = Callable[[list[str], str | None], subprocess.CompletedProcess]


def run_process(args: list[str], input: str | None = None, timeout: float = 900) -> subprocess.CompletedProcess:
    """shell=False, capture_output, text, encoding='utf-8', errors='replace', check=False."""
    return subprocess.run(
        args,
        input=input,
        timeout=timeout,
        shell=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )

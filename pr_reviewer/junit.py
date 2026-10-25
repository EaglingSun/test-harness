"""JUnit XML → TestReport(실행 testcase 수, 실패 목록) (R2). I/O는 입력 파일 읽기뿐."""

import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Sequence

from pr_reviewer.models import TestFailure, TestReport

_MAX_DETAILS = 4000  # 에이전트 프롬프트 크기 제한


class JUnitParseError(Exception):
    """JUnit XML 파싱 실패. 메시지에 파일 경로를 포함한다."""


def _to_int(value: str | None) -> int | None:
    try:
        return int(value) if value is not None else None
    except ValueError:
        return None


def _failure_of(case: ET.Element) -> TestFailure | None:
    for kind in ("failure", "error"):
        elem = case.find(kind)
        if elem is not None:
            return TestFailure(
                name=case.get("name", ""),
                classname=case.get("classname", ""),
                kind=kind,
                message=elem.get("message", ""),
                details=(elem.text or "")[:_MAX_DETAILS],
                file=case.get("file"),
                line=_to_int(case.get("line")),
            )
    return None


def parse_junit_files(paths: Sequence[Path]) -> TestReport:
    """여러 JUnit XML을 합쳐 TestReport(total, failures)로 반환."""
    total = 0
    failures: list[TestFailure] = []
    for path in paths:
        try:
            root = ET.parse(path).getroot()
        except ET.ParseError as e:
            raise JUnitParseError(f"{path}: {e}") from e
        for case in root.iter("testcase"):
            total += 1
            failure = _failure_of(case)
            if failure is not None:
                failures.append(failure)
    return TestReport(total=total, failures=tuple(failures))

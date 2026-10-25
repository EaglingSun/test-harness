"""test · reverify 단계: JUnit XML + base 판 기준 목록 → 분류(unexpected/fixed/missing). 판정하지 않는다 (ADR-006)."""

import argparse
import sys
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Sequence

from loop.contract import ContractError, write_stage
from pr_reviewer.proc import Runner, run_process

DEFAULT_EXPECT_PATH = "tests/expected_failures.txt"


class ReportError(Exception):
    """결과 XML 없음 · 파싱 실패 · testcase 0개 · git 실패. 계약에 status error 로 남긴다."""


def parse_results(results_dir: Path) -> dict[str, bool]:
    """`<results_dir>/*.xml` 의 모든 testcase → {`<스위트>::<케이스>`: 실패 여부}.

    식별자 · 실패 규칙은 vsm_test `tests/check_junit.py` parse_xml 과 같다:
    식별자 = <testsuite name>::<testcase name>, <failure> 또는 <error> 가 있으면 실패.
    """
    paths = sorted(Path(results_dir).glob("*.xml"))
    if not paths:
        raise ReportError(f"{results_dir}: 결과 XML 이 없다")
    outcomes: dict[str, bool] = {}
    for path in paths:
        try:
            root = ET.parse(path).getroot()
        except (ET.ParseError, OSError) as e:
            raise ReportError(f"{path}: XML 을 읽지 못했다 — {e}") from e
        for ts in root.iter("testsuite"):
            suite = ts.get("name")
            if not suite:
                raise ReportError(f"{path}: name 이 없는 testsuite 가 있다")
            for tc in ts.iter("testcase"):
                case = tc.get("name")
                if not case:
                    raise ReportError(f"{path}: name 이 없는 testcase 가 있다 (스위트 {suite})")
                failed = tc.find("failure") is not None or tc.find("error") is not None
                outcomes[f"{suite}::{case}"] = failed
    if not outcomes:
        raise ReportError(f"{results_dir}: testcase 가 하나도 없다")
    return outcomes


def parse_expect(text: str) -> list[str]:
    """빈 줄과 `#` 줄을 뺀 식별자 목록(정렬, 중복 제거)."""
    return sorted({s for s in (line.strip() for line in text.splitlines()) if s and not s.startswith("#")})


def classify(outcomes: dict[str, bool], expect: list[str]) -> dict[str, list[str]]:
    """base 기준 목록으로 분류한다. check_junit.py 의 ⓐⓑⓒ 와 같은 식이다."""
    expect_set = set(expect)
    all_ids = set(outcomes)
    failed = {i for i, f in outcomes.items() if f}
    return {
        "failed": sorted(failed),
        "unexpected": sorted(failed - expect_set),             # ⓐ
        "fixed": sorted((expect_set & all_ids) - failed),      # ⓑ
        "missing": sorted(expect_set - all_ids),               # ⓒ
    }


def _git(runner: Runner, workspace: str, *args: str) -> str:
    r = runner(["git", "-C", workspace, *args], None)
    if r.returncode != 0:
        raise ReportError(f"git {' '.join(args)} 실패: {(r.stderr or '').strip()}")
    return r.stdout or ""


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    p = argparse.ArgumentParser(prog="loop.test_report", description="JUnit 결과 분류 (판정하지 않음)")
    p.add_argument("--workspace", required=True)
    p.add_argument("--stage", choices=("test", "reverify"), required=True)
    p.add_argument("--make-outcome", required=True)
    p.add_argument("--base-ref", required=True)
    p.add_argument("--results")
    p.add_argument("--expect-path", default=DEFAULT_EXPECT_PATH)
    return p.parse_args(argv)


def main(argv: list[str] | None = None, runner: Runner = run_process) -> int:
    args = _parse_args(argv)
    ws = Path(args.workspace)
    results_dir = Path(args.results) if args.results else ws / "test-results"
    data: dict = {"stage": args.stage, "status": "ok", "make_outcome": args.make_outcome, "total": 0,
                  "failed": [], "unexpected": [], "fixed": [], "missing": [], "head_sha": "",
                  "expected_base": [], "expected_head": []}
    try:
        head_file = ws / args.expect_path
        if head_file.is_file():
            data["expected_head"] = parse_expect(head_file.read_text(encoding="utf-8"))
        data["head_sha"] = _git(runner, str(ws), "rev-parse", "HEAD").strip()
        outcomes = parse_results(results_dir)
        data["total"] = len(outcomes)
        data["expected_base"] = parse_expect(_git(runner, str(ws), "show", f"{args.base_ref}:{args.expect_path}"))
        data.update(classify(outcomes, data["expected_base"]))
    except ReportError as e:
        data["status"] = "error"
        data["reason"] = str(e)
        print(f"{args.stage}: {e}", file=sys.stderr)
    try:
        write_stage(ws / "out", args.stage, data)
    except (ContractError, OSError) as e:
        print(f"{args.stage}: 계약 파일을 쓰지 못했다 — {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())

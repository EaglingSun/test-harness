"""단계 간 계약 JSON(`out/<단계>.json`) 스키마 · 읽기/쓰기/검증 (ADR-006)."""

import json
import os
from pathlib import Path


class ContractError(Exception):
    """계약 파일 없음 · JSON 깨짐 · 필수 키 누락 · 타입 오류."""


_TEST_KEYS = ("stage", "status", "make_outcome", "total", "failed", "unexpected", "fixed", "missing",
              "head_sha", "expected_base", "expected_head")
_GATE_KEYS = ("stage", "gate", "go", "decision", "reason", "forced", "degraded")

STAGE_KEYS: dict[str, tuple[str, ...]] = {
    "test": _TEST_KEYS,
    "reverify": _TEST_KEYS,
    "review": ("stage", "status", "mode", "counts", "critical_by_category", "event", "posted", "errors"),
    "gate-autofix": _GATE_KEYS,
    "gate-merge": _GATE_KEYS,
    "gate-release": _GATE_KEYS,
    "fix": ("stage", "status", "mode", "action", "commit_sha", "attempt"),
    "merge": ("stage", "merged", "merge_sha", "noop"),
    "release": ("stage", "tag", "url", "prerelease", "reused", "degraded"),
}

STATUS_VALUES = ("ok", "error")
LIST_KEYS = ("failed", "unexpected", "fixed", "missing", "expected_base", "expected_head", "errors")
BOOL_KEYS = ("go", "forced", "degraded", "posted", "merged", "noop", "prerelease", "reused")


def stage_path(out_dir: Path, name: str) -> Path:
    return Path(out_dir) / f"{name}.json"


def validate(name: str, data: object) -> None:
    """필수 키 · stage 값 · status 값 · 목록/bool 타입을 검사한다. 어긋나면 ContractError."""
    if name not in STAGE_KEYS:
        raise ContractError(f"알 수 없는 단계 이름: {name!r}")
    if not isinstance(data, dict):
        raise ContractError(f"{name}: 계약은 JSON 객체여야 한다")
    missing = [k for k in STAGE_KEYS[name] if k not in data]
    if missing:
        raise ContractError(f"{name}: 필수 키 누락 {missing}")
    if data["stage"] != name:
        raise ContractError(f"{name}: stage 값이 {data['stage']!r} 이다")
    if "status" in data and data["status"] not in STATUS_VALUES:
        raise ContractError(f"{name}: status 는 ok/error 중 하나여야 한다: {data['status']!r}")
    for key in LIST_KEYS:
        if key in data and not (isinstance(data[key], list) and all(isinstance(v, str) for v in data[key])):
            raise ContractError(f"{name}: {key} 는 문자열 리스트여야 한다")
    for key in BOOL_KEYS:
        if key in data and not isinstance(data[key], bool):
            raise ContractError(f"{name}: {key} 는 bool 이어야 한다")


def write_stage(out_dir: Path, name: str, data: dict) -> Path:
    validate(name, data)
    path = stage_path(out_dir, name)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def read_stage(out_dir: Path, name: str) -> dict:
    path = stage_path(out_dir, name)
    if not path.is_file():
        raise ContractError(f"{path}: 계약 파일이 없다")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError, UnicodeDecodeError) as e:
        raise ContractError(f"{path}: JSON 을 읽지 못했다 — {e}") from e
    validate(name, data)
    return data


def write_github_output(key: str, value: str) -> None:
    """GITHUB_OUTPUT 환경변수가 있으면 `key=value` 줄을 덧붙인다. 없으면 아무것도 하지 않는다."""
    path = os.environ.get("GITHUB_OUTPUT")
    if not path:
        return
    with open(path, "a", encoding="utf-8") as f:
        f.write(f"{key}={value}\n")

"""unified diff 파싱 → 파일별 RIGHT side 코멘트 가능 라인 집합 (R1). I/O 없음."""

import re

_HUNK = re.compile(r"^@@ -\d+(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")


def parse_commentable_lines(diff_text: str) -> dict[str, set[int]]:
    """`gh pr diff` 형식의 unified diff → {새 파일 경로: RIGHT side에서 코멘트 가능한 줄 번호 집합}."""
    result: dict[str, set[int]] = {}
    path: str | None = None
    new_line = 0
    old_left = new_left = 0  # 현재 hunk에 남은 줄 수. 0이면 hunk 밖(헤더 영역)

    for raw in diff_text.splitlines():
        line = raw.rstrip("\r")
        if old_left > 0 or new_left > 0:
            # hunk 본문: 카운트로 경계를 판단해 "+++ "/"--- "로 시작하는 내용 줄도 헤더로 오인하지 않는다.
            if line.startswith("\\"):
                continue  # "\ No newline at end of file"
            tag = line[:1]
            if tag == "-":
                old_left -= 1
                continue
            if tag == "+":
                new_left -= 1
            else:  # context (" " 또는 공백이 잘린 빈 줄)
                old_left -= 1
                new_left -= 1
            if path is not None:
                result.setdefault(path, set()).add(new_line)
            new_line += 1
            continue

        if line.startswith("diff --git "):
            path = None
        elif line.startswith("+++ "):
            target = line[4:].split("\t", 1)[0]
            path = target[2:] if target.startswith("b/") else None  # /dev/null = 삭제 파일
        elif m := _HUNK.match(line):
            old_left = int(m.group(1)) if m.group(1) is not None else 1
            new_line = int(m.group(2))
            new_left = int(m.group(3)) if m.group(3) is not None else 1
    return result

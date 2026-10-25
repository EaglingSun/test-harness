"""diff.parse_commentable_lines 테스트 — `gh pr diff` 형식 unified diff에서 RIGHT side 코멘트 가능 라인을 계산한다."""

from pr_reviewer.diff import parse_commentable_lines


def test_single_hunk_addition():
    diff = (
        "diff --git a/app.py b/app.py\n"
        "index 1111111..2222222 100644\n"
        "--- a/app.py\n"
        "+++ b/app.py\n"
        "@@ -1,2 +1,3 @@\n"
        " a\n"
        "+b\n"
        " c\n"
    )
    assert parse_commentable_lines(diff) == {"app.py": {1, 2, 3}}


def test_multiple_hunks():
    diff = (
        "diff --git a/app.py b/app.py\n"
        "--- a/app.py\n"
        "+++ b/app.py\n"
        "@@ -1,2 +1,3 @@\n"
        " a\n"
        "+b\n"
        " c\n"
        "@@ -10,2 +11,3 @@ def f():\n"
        " x\n"
        "+y\n"
        " z\n"
    )
    assert parse_commentable_lines(diff) == {"app.py": {1, 2, 3, 11, 12, 13}}


def test_multiple_files():
    diff = (
        "diff --git a/a.py b/a.py\n"
        "--- a/a.py\n"
        "+++ b/a.py\n"
        "@@ -1 +1,2 @@\n"
        " one\n"
        "+two\n"
        "diff --git a/pkg/b.py b/pkg/b.py\n"
        "--- a/pkg/b.py\n"
        "+++ b/pkg/b.py\n"
        "@@ -5,1 +5,2 @@\n"
        " five\n"
        "+six\n"
    )
    assert parse_commentable_lines(diff) == {"a.py": {1, 2}, "pkg/b.py": {5, 6}}


def test_deleted_lines_do_not_advance_new_line_number():
    diff = (
        "diff --git a/app.py b/app.py\n"
        "--- a/app.py\n"
        "+++ b/app.py\n"
        "@@ -3,5 +3,4 @@\n"
        " keep3\n"
        "-old4\n"
        "-old5\n"
        "+new4\n"
        " keep5\n"
        "+new6\n"
        " keep7\n"
    )
    # 새 파일 기준: keep3=3, new4=4, keep5=5, new6=6, keep7=7
    assert parse_commentable_lines(diff) == {"app.py": {3, 4, 5, 6, 7}}


def test_new_file():
    diff = (
        "diff --git a/new.py b/new.py\n"
        "new file mode 100644\n"
        "index 0000000..3333333\n"
        "--- /dev/null\n"
        "+++ b/new.py\n"
        "@@ -0,0 +1,3 @@\n"
        "+l1\n"
        "+l2\n"
        "+l3\n"
    )
    assert parse_commentable_lines(diff) == {"new.py": {1, 2, 3}}


def test_deleted_file_excluded():
    diff = (
        "diff --git a/gone.py b/gone.py\n"
        "deleted file mode 100644\n"
        "--- a/gone.py\n"
        "+++ /dev/null\n"
        "@@ -1,2 +0,0 @@\n"
        "-x\n"
        "-y\n"
        "diff --git a/keep.py b/keep.py\n"
        "--- a/keep.py\n"
        "+++ b/keep.py\n"
        "@@ -1 +1 @@\n"
        "-old\n"
        "+new\n"
    )
    assert parse_commentable_lines(diff) == {"keep.py": {1}}


def test_rename_uses_new_path():
    diff = (
        "diff --git a/old/name.py b/new/name.py\n"
        "similarity index 90%\n"
        "rename from old/name.py\n"
        "rename to new/name.py\n"
        "--- a/old/name.py\n"
        "+++ b/new/name.py\n"
        "@@ -1,2 +1,2 @@\n"
        " same\n"
        "-before\n"
        "+after\n"
    )
    assert parse_commentable_lines(diff) == {"new/name.py": {1, 2}}


def test_hunk_header_without_count():
    diff = (
        "diff --git a/one.txt b/one.txt\n"
        "--- a/one.txt\n"
        "+++ b/one.txt\n"
        "@@ -7 +7 @@\n"
        "-old\n"
        "+new\n"
    )
    assert parse_commentable_lines(diff) == {"one.txt": {7}}


def test_no_newline_marker_ignored():
    diff = (
        "diff --git a/f.txt b/f.txt\n"
        "--- a/f.txt\n"
        "+++ b/f.txt\n"
        "@@ -1,2 +1,3 @@\n"
        " a\n"
        "-b\n"
        "\\ No newline at end of file\n"
        "+b\n"
        "+c\n"
        "\\ No newline at end of file\n"
    )
    assert parse_commentable_lines(diff) == {"f.txt": {1, 2, 3}}


def test_binary_file_excluded():
    diff = (
        "diff --git a/img.png b/img.png\n"
        "index 1111111..2222222 100644\n"
        "Binary files a/img.png and b/img.png differ\n"
        "diff --git a/t.py b/t.py\n"
        "--- a/t.py\n"
        "+++ b/t.py\n"
        "@@ -1 +1,2 @@\n"
        " a\n"
        "+b\n"
    )
    assert parse_commentable_lines(diff) == {"t.py": {1, 2}}


def test_crlf_line_endings():
    diff = (
        "diff --git a/w.py b/w.py\r\n"
        "--- a/w.py\r\n"
        "+++ b/w.py\r\n"
        "@@ -1,2 +1,3 @@\r\n"
        " a\r\n"
        "+b\r\n"
        " c\r\n"
    )
    assert parse_commentable_lines(diff) == {"w.py": {1, 2, 3}}


def test_empty_diff():
    assert parse_commentable_lines("") == {}

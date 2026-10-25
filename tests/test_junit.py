"""junit.py 테스트 — tmp_path에 JUnit XML을 써서 파싱 결과를 검증한다 (R2)."""

from pathlib import Path

import pytest

from pr_reviewer.junit import JUnitParseError, parse_junit_files
from pr_reviewer.models import TestFailure, TestReport


def _write(tmp_path: Path, name: str, content: str) -> Path:
    path = tmp_path / name
    path.write_text(content, encoding="utf-8")
    return path


PYTEST_XML = """<?xml version="1.0" encoding="utf-8"?>
<testsuites>
  <testsuite name="pytest" tests="4" failures="1" errors="1" skipped="1">
    <testcase classname="tests.test_calc" name="test_add" file="tests/test_calc.py" line="10" time="0.001"/>
    <testcase classname="tests.test_calc" name="test_div_zero" file="tests/test_calc.py" line="20">
      <failure message="assert 1 == 0">def test_div_zero():
&gt;       assert divide(1, 0) == 0
E       assert 1 == 0</failure>
    </testcase>
    <testcase classname="tests.test_calc" name="test_io" file="tests/test_calc.py" line="30">
      <error message="fixture 'db' not found">E       fixture 'db' not found</error>
    </testcase>
    <testcase classname="tests.test_calc" name="test_skip">
      <skipped message="not ready"/>
    </testcase>
  </testsuite>
</testsuites>
"""


def test_pytest_format_mixed_results(tmp_path):
    report = parse_junit_files([_write(tmp_path, "pytest.xml", PYTEST_XML)])

    assert isinstance(report, TestReport)
    assert report.total == 4
    assert report.failures == (
        TestFailure(
            name="test_div_zero",
            classname="tests.test_calc",
            kind="failure",
            message="assert 1 == 0",
            details="def test_div_zero():\n>       assert divide(1, 0) == 0\nE       assert 1 == 0",
            file="tests/test_calc.py",
            line=20,
        ),
        TestFailure(
            name="test_io",
            classname="tests.test_calc",
            kind="error",
            message="fixture 'db' not found",
            details="E       fixture 'db' not found",
            file="tests/test_calc.py",
            line=30,
        ),
    )


def test_single_testsuite_root(tmp_path):
    xml = """<testsuite name="s" tests="2">
  <testcase classname="A" name="ok"/>
  <testcase classname="A" name="bad"><failure message="boom"/></testcase>
</testsuite>"""
    report = parse_junit_files([_write(tmp_path, "s.xml", xml)])

    assert report.total == 2
    assert len(report.failures) == 1
    f = report.failures[0]
    assert (f.name, f.classname, f.kind, f.message) == ("bad", "A", "failure", "boom")
    assert f.details == ""  # 텍스트 없음 → ""


def test_nested_testsuites_are_all_traversed(tmp_path):
    xml = """<testsuites>
  <testsuite name="outer">
    <testcase classname="O" name="t1"/>
    <testsuite name="inner">
      <testcase classname="I" name="t2"><error message="e"/></testcase>
    </testsuite>
  </testsuite>
</testsuites>"""
    report = parse_junit_files([_write(tmp_path, "n.xml", xml)])

    assert report.total == 2
    assert [(f.name, f.kind) for f in report.failures] == [("t2", "error")]


def test_missing_file_line_and_message_attributes(tmp_path):
    xml = """<testsuite><testcase classname="C" name="t"><failure>trace</failure></testcase></testsuite>"""
    f = parse_junit_files([_write(tmp_path, "a.xml", xml)]).failures[0]

    assert f.file is None
    assert f.line is None
    assert f.message == ""
    assert f.details == "trace"


def test_non_integer_line_becomes_none(tmp_path):
    xml = """<testsuite><testcase classname="C" name="t" file="x.py" line="abc">
<failure message="m"/></testcase></testsuite>"""
    f = parse_junit_files([_write(tmp_path, "a.xml", xml)]).failures[0]

    assert f.file == "x.py"
    assert f.line is None


def test_multiple_files_are_summed_in_order(tmp_path):
    a = _write(tmp_path, "a.xml", PYTEST_XML)
    b = _write(tmp_path, "b.xml", """<testsuite>
  <testcase classname="B" name="b1"/>
  <testcase classname="B" name="b2"><failure message="x"/></testcase>
</testsuite>""")
    report = parse_junit_files([a, b])

    assert report.total == 6
    assert [f.name for f in report.failures] == ["test_div_zero", "test_io", "b2"]


def test_details_truncated_to_4000_chars(tmp_path):
    long_text = "x" * 5000
    xml = f"""<testsuite><testcase classname="C" name="t"><failure message="m">{long_text}</failure></testcase></testsuite>"""
    f = parse_junit_files([_write(tmp_path, "a.xml", xml)]).failures[0]

    assert len(f.details) == 4000
    assert f.details == "x" * 4000


def test_broken_xml_raises_with_path(tmp_path):
    good = _write(tmp_path, "good.xml", PYTEST_XML)
    bad = _write(tmp_path, "bad.xml", "<testsuite><testcase name='t'>")

    with pytest.raises(JUnitParseError) as exc:
        parse_junit_files([good, bad])

    assert str(bad) in str(exc.value)


def test_empty_paths_returns_empty_report():
    assert parse_junit_files([]) == TestReport(total=0, failures=())

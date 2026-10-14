"""Contract tests for scripts/trivial_wrappers.py."""

from __future__ import annotations

from pathlib import Path

import pytest
import trivial_wrappers

FIXTURES = Path(__file__).parent / "fixtures" / "trivial_wrappers"


def findings(source: str) -> list[tuple[str, str, int]]:
    """(kind, name, call sites) per finding, in source order."""
    return [(f.kind, f.name, f.call_sites) for f in trivial_wrappers.check(source)]


class TestTrivialWrapper:
    @pytest.mark.parametrize(
        "body",
        [
            "return g(x)",
            "return x.attr",
            "return 3",
            "return [x, x]",
            "return [i for i in x]",
            "g(x)",
            "y = g(x)",
        ],
    )
    def test_one_statement_of_each_listed_value_kind_is_flagged(self, body):
        source = f"def f(x):\n    {body}\n\n\nf(1)\nf(2)\n"
        assert findings(source) == [("trivial-wrapper", "f", 2)]

    def test_docstring_does_not_count_as_a_statement(self):
        source = 'def f(x):\n    """Doc."""\n    return g(x)\n\n\nf(1)\nf(2)\n'
        assert findings(source) == [("trivial-wrapper", "f", 2)]

    @pytest.mark.parametrize(
        "body",
        ["y = g(x)\n    return y", "return x + 1", "return x", "pass"],
    )
    def test_real_logic_is_not_flagged(self, body):
        source = f"def f(x):\n    {body}\n\n\nf(1)\nf(2)\n"
        assert findings(source) == []

    def test_methods_are_excluded(self):
        source = "class C:\n    def m(self):\n        return g()\n\n    def _n(self):\n        return 1\n"
        assert findings(source) == []

    def test_nested_function_is_checked(self):
        source = (
            "def outer(a):\n"
            "    def inner(x):\n"
            "        return g(x)\n"
            "    y = inner(a)\n"
            "    return inner(y), a + 1\n"
        )
        assert findings(source) == [("trivial-wrapper", "inner", 2)]


class TestSingleUseHelper:
    def test_private_function_used_once_is_flagged(self):
        source = "def _h(x):\n    y = x + 1\n    return y\n\n\ndef run():\n    return _h(1)\n"
        assert ("single-use-helper", "_h", 1) in findings(source)

    def test_private_function_used_twice_is_not(self):
        source = "def _h(x):\n    y = x + 1\n    return y\n\n\ndef run():\n    a = _h(1)\n    return _h(a)\n"
        assert findings(source) == []

    def test_nested_function_used_once_is_flagged(self):
        source = (
            "def run(a):\n"
            "    def step(x):\n"
            "        y = x + 1\n"
            "        return y\n"
            "    return step(a)\n"
        )
        assert findings(source) == [("single-use-helper", "step", 1)]

    def test_public_module_function_used_once_is_not(self):
        source = "def h(x):\n    y = x + 1\n    return y\n\n\nrun = h(1)\n"
        assert findings(source) == []

    def test_trivial_and_single_use_reports_the_wrapper_kind_once(self):
        source = "def _h(x):\n    return g(x)\n\n\ndef run():\n    a = _h(1)\n    return a + 1\n"
        assert findings(source) == [("trivial-wrapper", "_h", 1)]


class TestEntryPointExemption:
    MAIN = "\n\nif __name__ == '__main__':\n    print(run())\n"

    def test_public_function_called_from_main_block_is_exempt(self):
        source = "def run():\n    return g()\n" + self.MAIN
        assert findings(source) == []

    def test_private_function_called_from_main_block_is_not_exempt(self):
        source = (
            "def _run():\n    return g()\n\n\nif __name__ == '__main__':\n    _run()\n"
        )
        assert findings(source) == [("trivial-wrapper", "_run", 1)]


class TestMarker:
    def test_reasoned_marker_silences_the_finding(self):
        source = "def f(x):  # wrapper-ok: names the units\n    return g(x)\n\n\nf(1)\nf(2)\n"
        assert findings(source) == []

    def test_bare_marker_is_itself_a_finding(self):
        source = "def f(x):  # wrapper-ok\n    return g(x)\n\n\nf(1)\nf(2)\n"
        assert findings(source) == [("bare-marker", "f", 2)]

    def test_bare_marker_on_a_function_that_is_otherwise_fine_is_flagged(self):
        source = (
            "def f(x):  # wrapper-ok:\n    y = x + 1\n    return y\n\n\nf(1)\nf(2)\n"
        )
        assert findings(source) == [("bare-marker", "f", 2)]


class TestCli:
    def test_output_format_and_report_mode_exit_zero(self, tmp_path, capsys):
        path = tmp_path / "m.py"
        path.write_text("def f(x):\n    return g(x)\n\n\nf(1)\nf(2)\n")
        assert trivial_wrappers.main([str(path)]) == 0
        assert capsys.readouterr().out.splitlines() == [
            f"{path}:1: trivial-wrapper: f (2 call sites)"
        ]

    def test_gate_exits_one_on_a_finding_and_zero_on_none(self, tmp_path):
        bad = tmp_path / "bad.py"
        bad.write_text("def f(x):\n    return g(x)\n")
        good = tmp_path / "good.py"
        good.write_text("def f(x):\n    y = x + 1\n    return y\n")
        assert trivial_wrappers.main(["--gate", str(bad)]) == 1
        assert trivial_wrappers.main(["--gate", str(good)]) == 0

    def test_directory_is_walked(self, tmp_path, capsys):
        (tmp_path / "a.py").write_text("def f(x):\n    return g(x)\n")
        trivial_wrappers.main([str(tmp_path)])
        assert "a.py:1: trivial-wrapper: f" in capsys.readouterr().out

    def test_unparseable_file_fails_rather_than_passing_silently(self, tmp_path):
        path = tmp_path / "broken.py"
        path.write_text("def f(:\n")
        assert trivial_wrappers.main([str(path)]) == 1


class TestRealScripts:
    def test_pre_cleanup_example_flags_its_one_use_helpers(self):
        source = (FIXTURES / "antisymmetric_xx.py").read_text()
        names = {f.name for f in trivial_wrappers.check(source)}
        assert {
            "_config",
            "_dipolar",
            "_nn_native",
            "_z_rotation",
            "_half_sequence",
            "make_pulse",
        } <= names

    def test_cleaned_example_has_no_findings(self):
        source = (FIXTURES / "nnn_dipolar_xx.py").read_text()
        assert trivial_wrappers.check(source) == []


class TestExemptions:
    @pytest.mark.parametrize(
        "source",
        [
            "@register\ndef _f():\n    return g()\n",
            "@pytest.fixture\ndef data():\n    return g()\n",
            "@overload\ndef f(x: int) -> int: ...\n\n\nf(1)\nf(2)\n",
            "def f(x):\n    ...\n\n\nf(1)\nf(2)\n",
            'def f(x):\n    """Only a docstring."""\n\n\nf(1)\nf(2)\n',
            "def f(x):\n    pass\n\n\nf(1)\nf(2)\n",
            "def test_it():\n    assert g()\n    return g()\n",
            "def test_thing():\n    g()\n",
        ],
    )
    def test_not_a_wrapper(self, source):
        assert findings(source) == []


class TestMinors:
    def test_marker_on_closing_line_of_a_multiline_def(self):
        source = "def f(\n    x,\n):  # wrapper-ok: names the unit\n    return g(x)\n\n\nf(1)\nf(2)\n"
        assert findings(source) == []

    def test_recursion_is_not_a_use(self):
        source = "def _f(n):\n    y = n - 1\n    return _f(y)\n\n\ndef run():\n    a = _f(3)\n    return a + 1\n"
        assert findings(source) == [("single-use-helper", "_f", 1)]


class TestRound2:
    @pytest.mark.parametrize("body", ["...", "pass", '"""Doc only."""'])
    def test_private_stub_used_once_is_not_a_helper(self, body):
        source = (
            f"def _f():\n    {body}\n\n\ndef run():\n    a = _f()\n    return a + 1\n"
        )
        assert findings(source) == []

    def test_marker_when_one_line_body_is_on_the_closing_line(self):
        source = "def f(\n    x,\n):  # wrapper-ok: names the unit\n    return g(x)\n"
        assert findings(source) == []
        source = "def f(\n    x,\n): return g(x)  # wrapper-ok: names the unit\n"
        assert findings(source) == []

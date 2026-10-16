"""Contract tests for scripts/plain_math.py."""

from __future__ import annotations

from pathlib import Path

import plain_math
import pytest

PLOT = "import matplotlib.pyplot as plt\n"


def tokens(findings) -> list[tuple[str, str]]:
    return [(f.kind, f.token) for f in findings]


def py(body: str) -> list[tuple[str, str]]:
    return tokens(plain_math.check_python(PLOT + body))


class TestStandIns:
    @pytest.mark.parametrize(
        ("text", "kind", "token", "suggestion"),
        [
            ("loop phase phi", "greek", "phi", r"$\phi$"),
            ("Gamma point", "greek", "Gamma", r"$\Gamma$"),
            ("3pi/2", "pi-multiple", "3pi/2", r"$3\pi/2$"),
            ("pi / 4", "pi-multiple", "pi / 4", r"$\pi / 4$"),
            ("2pi", "pi-multiple", "2pi", r"$2\pi$"),
            (
                "mean |<kappa_b>|",
                "magnitude",
                "|<kappa_b>|",
                r"$|\langle \kappa_b \rangle|$",
            ),
            ("<n_i>", "expectation", "<n_i>", r"$\langle n_i \rangle$"),
            ("J_1 coupling", "subscript", "J_1", r"$J_1$"),
            ("x^2", "superscript", "x^2", r"$x^2$"),
            ("gap E1", "digit-subscript", "E1", r"$E_1$"),
            ("exp(-i t)", "function", "exp(", r"$\exp($"),
        ],
    )
    def test_each_kind_is_found_with_a_math_suggestion(
        self, text, kind, token, suggestion
    ):
        assert [f[1:] for f in plain_math.stand_ins(text, typst=False)] == [
            (kind, token, suggestion)
        ]

    def test_typst_suggestions_use_typst_math(self):
        found = list(plain_math.stand_ins("|<kappa_b>| and varphi", typst=True))
        assert [f[3] for f in found] == [
            "$|chevron.l kappa_b chevron.r|$",
            "$phi.alt$",
        ]

    @pytest.mark.parametrize(
        "text",
        [
            "the alphabet and epsilonic pipeline",
            "Fig. S1 and Table A2",
            "version v1.2",
            "r < 3 and r > 1",
            "a | b",
            "machine epsilon",
            "train_loss",
            "4x4 torus",
        ],
    )
    def test_ordinary_words_are_not_stand_ins(self, text):
        assert list(plain_math.stand_ins(text, typst=False)) == []


class TestPython:
    def test_literal_at_each_label_site_is_flagged(self):
        body = (
            "ax.set_xlabel('phi / pi')\n"
            "ax.set_title('mean |<kappa_b>|')\n"
            "ax.text(0.5, 0.5, '+phi')\n"
            "ax.annotate('rho', (0, 0))\n"
            "ax.set_xticks([0, 1], labels=['0', '3pi/2'])\n"
            "fig.colorbar(m, label='kappa')\n"
            "ax.plot(x, y, label='J1')\n"
        )
        assert py(body) == [
            ("greek", "phi"),
            ("greek", "pi"),
            ("magnitude", "|<kappa_b>|"),
            ("greek", "phi"),
            ("greek", "rho"),
            ("pi-multiple", "3pi/2"),
            ("greek", "kappa"),
            ("digit-subscript", "J1"),
        ]

    def test_mathtext_is_not_flagged(self):
        assert (
            py(r"ax.set_title(r'mean $|\langle\kappa_b\rangle|$ at $\phi = \pi$')")
            == []
        )

    def test_strings_away_from_label_sites_are_ignored(self):
        body = "data['kappa_far']\nkey = 'phi'\nprint('rho')\nax.plot(x, color='pi')\n"
        assert py(body) == []

    def test_label_traced_through_a_loop_over_appended_tuples(self):
        body = (
            "def columns():\n"
            "    cols = [('k', 'mean |<kappa_b>|')]\n"
            "    cols.append(('g', 'gap E1'))\n"
            "    return cols\n"
            "cols = columns()\n"
            "for c, (key, title) in enumerate(cols):\n"
            "    ax.set_title(title)\n"
        )
        assert py(body) == [("magnitude", "|<kappa_b>|"), ("digit-subscript", "E1")]

    def test_conditional_and_fstring_parts_are_read(self):
        body = "ax.text(0, 0, '+phi' if s else '-phi')\nax.plot(x, label=f'{n} rho')\n"
        assert py(body) == [("greek", "phi"), ("greek", "phi"), ("greek", "rho")]

    def test_non_plotting_module_is_skipped(self):
        assert plain_math.check_python("st.title('phi')\nx = dict(label='rho')\n") == []

    def test_marker_with_reason_silences_and_bare_marker_is_a_finding(self):
        body = (
            "ax.set_title('phi')  # math-ok: names the variable in the code\n"
            "ax.set_xlabel('rho')  # math-ok\n"
        )
        assert py(body) == [("bare-marker", "math-ok")]


class TestTypst:
    def check(self, source: str) -> list[tuple[str, str]]:
        return tokens(plain_math.check_typst(source))

    def test_prose_stand_ins_are_flagged_and_math_is_not(self):
        source = "The phase phi sets $phi$, with |J2| and 3pi/2.\n"
        assert self.check(source) == [
            ("greek", "phi"),
            ("magnitude", "|J2|"),
            ("pi-multiple", "3pi/2"),
        ]

    def test_code_raw_comments_labels_and_refs_are_skipped(self):
        source = (
            '#let phi = json("pi/rho.json")\n'
            '#set text(font: "Rho")\n'
            "See `kappa_b` and @fig-phi. // phi here\n"
            "= Heading <sec-rho>\n"
            '#image("figs/phi.pdf")\n'
            "/* pi */ ok\n"
        )
        assert self.check(source) == []

    def test_content_blocks_and_caption_strings_are_prose(self):
        source = (
            '#figure(image("x.pdf"), caption: [Loop phase phi.]) <fig-x>\n'
            '#show: theme.with(title: "The J1-J2 model", path: "J1.typ")\n'
        )
        assert self.check(source) == [
            ("greek", "phi"),
            ("digit-subscript", "J1"),
            ("digit-subscript", "J2"),
        ]

    def test_statement_inside_content_block_does_not_swallow_its_bracket(self):
        source = '#table([#if c [A] else [B]], ("J1-J2"))\n#let x = 1\n'
        assert self.check(source) == []

    def test_marker_comment_silences_its_line(self):
        assert self.check("beta testers // math-ok: English word\n") == []
        assert self.check("beta testers\n") == [("greek", "beta")]


class TestLatex:
    def check(self, source: str) -> list[tuple[str, str]]:
        return tokens(plain_math.check_latex(source))

    def test_prose_stand_ins_are_flagged_and_math_is_not(self):
        source = (
            "\\begin{document}\n"
            "The J1/J2 model at $\\phi$ and \\(rho\\) has phi.\n"
            "\\begin{equation} pi \\end{equation}\n"
            "\\end{document}\n"
        )
        assert self.check(source) == [
            ("digit-subscript", "J1"),
            ("digit-subscript", "J2"),
            ("greek", "phi"),
        ]

    def test_preamble_keys_paths_and_verbatim_are_skipped(self):
        source = (
            "\\newcommand{\\phase}{phi}\n"
            "\\begin{document}\n"
            "See Fig.~\\ref{fig:phi} \\cite{rho2020} % pi\n"
            "\\includegraphics[width=1in]{figs/kappa_b.pdf}\n"
            "\\begin{verbatim} phi \\end{verbatim}\n"
            "\\begin{tabular}{l|c|r} a \\end{tabular}\n"
            "\\verb|rho|\n"
            "\\end{document}\n"
        )
        assert self.check(source) == []

    def test_escaped_underscore_is_still_a_subscript(self):
        assert self.check("Coupling J\\_1 here.\n") == [("subscript", "J\\_1")]


class TestCli:
    def test_gate_fails_on_findings_and_report_mode_does_not(self, tmp_path, capsys):
        (tmp_path / "a.typ").write_text("phase phi\n", encoding="utf-8")
        (tmp_path / "b.tex").write_text("$\\phi$\n", encoding="utf-8")
        assert plain_math.main([str(tmp_path)]) == 0
        assert plain_math.main(["--gate", str(tmp_path / "*.typ")]) == 1
        assert plain_math.main(["--gate", str(tmp_path / "b.tex")]) == 0
        out = capsys.readouterr().out
        assert f'{Path(tmp_path, "a.typ")}:1:7: greek: "phi" -> $phi$' in out

    def test_unparsable_file_fails_in_both_modes(self, tmp_path):
        bad = tmp_path / "bad.py"
        bad.write_text("def (:\n", encoding="utf-8")
        assert plain_math.main([str(bad)]) == 1

    def test_build_directories_are_not_searched(self, tmp_path):
        (tmp_path / "build").mkdir()
        (tmp_path / "build" / "gen.typ").write_text("phi\n", encoding="utf-8")
        assert plain_math.main(["--gate", str(tmp_path)]) == 0

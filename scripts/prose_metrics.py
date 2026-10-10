#!/usr/bin/env python
"""Report deterministic size metrics for scientific prose (LaTeX, Typst, Markdown).

Usage:
    python scripts/prose_metrics.py FILE [--json]

Reports paragraph and sentence budgets, caption lengths, numeric literals
shared between captions and body text, words and sentences per section, the
distribution of words per sentence (median, 90th percentile, share over
``LONG_SENTENCE_WORDS``), the chained-clause rate, and the five longest
sentences with their source line numbers. It is a report, not a gate: the
exit code is 0 whenever the file parses.

Deliberately crude, so the numbers are reproducible rather than correct:

- A paragraph is a blank-line-separated block of body text. The LaTeX
  preamble, comments, display math, figure/table environments, Typst
  ``$ ... $`` lines and ``#figure(...)`` calls, and Markdown fenced code are
  dropped. A LaTeX file with no ``\\begin{document}`` is all body, so section
  fragments can be measured.
- A sentence ends at ``.``, ``?`` or ``!`` followed by whitespace and an
  uppercase letter or backslash. Abbreviations such as "Fig. Two" therefore
  split wrongly, and a sentence starting with a digit or lowercase letter
  does not split.
- A word is a whitespace-separated token with a letter or digit, after
  commands are dropped and their text arguments kept. Inline math is one word.
- A sentence is chained when, outside inline math and references, it holds
  ``;``, a lowercase word followed by ``: ``, or a dash (``---``, an em dash,
  or `` -- `` with spaces). A colon after a capitalised word ("Note: ...")
  or a bare ``--`` range does not count.
- The 90th percentile is nearest-rank, so it is always a sentence's own length.
- A sentence's line is found by searching the source, from the previous
  sentence onward, for its first few words. A sentence whose opening is split
  by a comment, or rewritten by dropped math, falls back to the previous
  sentence's line.
- Numeric literals inside \\ref, \\label, \\cite or \\eqref arguments (and
  Typst ``@label`` references) are ignored, as are bare single digits 0-9:
  those are too common to signal that a caption repeats the body.
"""

from __future__ import annotations

import argparse
import json
import math
import re
import statistics
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

PARAGRAPH_BUDGET_WORDS = 120
SENTENCE_BUDGET = 5
LONG_SENTENCE_WORDS = 30
LONGEST_SHOWN = 5

LATEX, TYPST, MARKDOWN = ".tex", ".typ", ".md"

# A "-" is a sign only when no digit, "-", "}" or ")" precedes it, so "3--5" is
# a range of 3 and 5 while "10^{-3}" keeps -3.
NUMERIC = re.compile(r"(?:(?<![\d\-})])-)?\d+(?:\.\d+)?(?:[eE]-?\d+)?")
SENTENCE_END = re.compile(r"(?<=[.?!])\s+(?=[A-Z\\])")
LATEX_REFS = re.compile(
    r"\\(?:ref|label|cite\w*|eqref|autoref|cref)\*?(?:\[[^\]]*\])?\{[^}]*\}"
)
TYPST_REFS = re.compile(r"@[\w:.-]+")
# A semicolon, a lowercase word then a colon, or a dash used as punctuation.
CHAINED = re.compile(r";|(?<!\w)[a-z]\w*:\s|---|\u2014|\s--\s")
INLINE_MATH = re.compile(r"\$[^$]*\$|\\\(.*?\\\)")
LATEX_COMMAND = re.compile(r"\\[A-Za-z]+\*?(?:\[[^\]]*\])?")
LATEX_ENV_MARKER = re.compile(r"\\(?:begin|end)\{[^}]*\}")
LATEX_LINE_BREAK = re.compile(r"\\\\(?:\[[^\]]*\])?")
TYPST_SETUP = re.compile(r"^[ \t]*#(?:set|show|import|let)\b")
TYPST_COMMAND = re.compile(r"#[A-Za-z][\w.]*")
LATEX_FLOATS = (
    "figure",
    "table",
    "wrapfigure",
    "wraptable",
    "sidewaysfigure",
    "sidewaystable",
    "subfigure",
)
LATEX_DISPLAY_MATH = (
    "equation",
    "align",
    "gather",
    "multline",
    "eqnarray",
    "subequations",
)


def latex_envs(names: tuple[str, ...]) -> str:
    """Regex source matching a whole environment, starred or not."""
    return rf"\\begin\{{((?:{'|'.join(names)})\*?)\}}.*?\\end\{{\1\}}"


# `\\[2pt]` is a line break, not the start of display math. A dropped block
# takes its own line ending with it and leaves a space, so one inside a
# paragraph does not split it; real paragraph breaks keep their blank lines.
LATEX_DROPPED = re.compile(
    r"(?:^[ \t]*)?(?:"
    + latex_envs(LATEX_FLOATS + LATEX_DISPLAY_MATH)
    + r"|(?<!\\)\\\[.*?\\\]|\$\$.*?\$\$)(?:[ \t]*$\n?)?",
    re.DOTALL | re.MULTILINE,
)
TYPST_DISPLAY_MATH = re.compile(r"^[ \t]*\$[^$]*\$[ \t]*$\n?", re.DOTALL | re.MULTILINE)
MD_FENCE = re.compile(r"^(```|~~~).*?^\1[ \t]*$\n?", re.DOTALL | re.MULTILINE)
LATEX_ENV = re.compile(latex_envs(LATEX_FLOATS), re.DOTALL)
TYPST_LABEL = re.compile(r"^[ \t]*<[\w:.-]+>")
LATEX_LABEL = re.compile(r"\\label\{([^}]*)\}")
# Group 1 is the comment-only line, removed whole so it cannot split a
# paragraph; a trailing comment leaves its line's text.
LATEX_COMMENT = re.compile(r"^[ \t]*(?<!\\)%.*\n?|(?<!\\)%.*", re.MULTILINE)
TYPST_COMMENT = re.compile(r"^[ \t]*//.*\n?|(?<!:)//.*", re.MULTILINE)

HEADINGS = {
    LATEX: re.compile(
        r"^[ \t]*\\(?:(?:sub){0,2}section|chapter)\*?(?:\[[^\]]*\])?\{(?P<t>[^}]*)\}"
    ),
    TYPST: re.compile(r"^=+\s+(?P<t>.*)$"),
    MARKDOWN: re.compile(r"^#{1,6}\s+(?P<t>.*)$"),
}


def balanced(text: str, start: int, opener: str, closer: str) -> tuple[str, int]:
    """The text inside a delimiter pair opened just before `start`, and its end.

    Brackets inside `$...$` do not count (`$[0, 1)$`). Raises ValueError when
    the pair never closes; callers decide what an unclosed pair means.
    """
    depth = 1
    math_end = -1
    for i in range(start, len(text)):
        if i < math_end:
            continue
        if text[i] == "$" and text[i - 1] != "\\":
            math_end = text.find("$", i + 1) + 1
        elif text[i] == opener:
            depth += 1
        elif text[i] == closer:
            depth -= 1
            if depth == 0:
                return text[start:i], i + 1
    raise ValueError(f"unbalanced {opener!r} starting at offset {start - 1}")


def strip_comments(text: str, kind: str) -> str:
    if kind == LATEX:
        return LATEX_COMMENT.sub("", text)
    if kind == TYPST:
        return TYPST_COMMENT.sub("", text)
    return text


def body_of(text: str, kind: str) -> str:
    """The text a reader sees as prose-or-captions, minus comments and preamble."""
    text = strip_comments(text, kind)
    if kind == LATEX:
        begin = text.find("\\begin{document}")
        if begin != -1:
            text = text[begin + len("\\begin{document}") :]
        end = text.find("\\end{document}")
        if end != -1:
            text = text[:end]
    return text


def caption_at(
    body: str, m: re.Match[str], opener: str, closer: str
) -> list[tuple[int, str]]:
    """The caption opened by match `m`, or nothing when it never closes.

    An unclosed caption is skipped rather than raised: the report is exit 0
    whenever the file is readable.
    """
    try:
        inner, _ = balanced(body, m.end(), opener, closer)
    except ValueError:
        return []
    return [(m.start(), inner)]


def captions_of(body: str, kind: str) -> list[tuple[str | int, str]]:
    """(label, raw text) for every caption.

    The label is the LaTeX \\label in the caption's float environment, else
    the caption's 1-based index.
    """
    found: list[tuple[int, str]] = []
    if kind == LATEX:
        for m in re.finditer(r"\\caption\*?(?:\[[^\]]*\])?\{", body):
            found.extend(caption_at(body, m, "{", "}"))
    elif kind == TYPST:
        for m in re.finditer(r"caption:\s*\[", body):
            found.extend(caption_at(body, m, "[", "]"))
    envs = [m.span() for m in LATEX_ENV.finditer(body)] if kind == LATEX else []
    captions: list[tuple[str | int, str]] = []
    for index, (offset, text) in enumerate(found, start=1):
        label = next(
            (
                m.group(1)
                for lo, hi in envs
                if lo <= offset < hi and (m := LATEX_LABEL.search(body[lo:hi]))
            ),
            index,
        )
        captions.append((label, text))
    return captions


def without_refs(text: str) -> str:
    return TYPST_REFS.sub(" ", LATEX_REFS.sub(" ", text))


def words(text: str, kind: str) -> int:
    text = INLINE_MATH.sub(" MATH ", without_refs(text))
    if kind == LATEX:
        text = LATEX_ENV_MARKER.sub(" ", LATEX_LINE_BREAK.sub(" ", text))
        text = LATEX_COMMAND.sub(" ", text).replace("{", " ").replace("}", " ")
        text = text.replace("~", " ")
    elif kind == TYPST:
        text = TYPST_COMMAND.sub(" ", text).replace("[", " ").replace("]", " ")
    return sum(1 for token in text.split() if re.search(r"\w", token))


def numerics(text: str) -> set[str]:
    return {
        n for n in NUMERIC.findall(without_refs(text)) if not re.fullmatch(r"\d", n)
    }


def without_typst_setup(body: str) -> str:
    """The body minus `#set`/`#show`/`#import`/`#let` lines and their continuations."""
    kept: list[str] = []
    depth = 0
    for line in body.splitlines():
        if depth > 0 or TYPST_SETUP.match(line):
            depth = max(depth + line.count("(") - line.count(")"), 0)
        else:
            kept.append(line)
    return "\n".join(kept)


def prose_blocks(body: str, kind: str) -> tuple[list[str], list[tuple[int, str]]]:
    """Section titles (index 0 is the untitled lead-in), and (section index,
    paragraph text) for each paragraph."""
    if kind == LATEX:
        body = LATEX_DROPPED.sub(" ", body)
    elif kind == TYPST:
        body = without_typst_setup(TYPST_DISPLAY_MATH.sub(" ", body))
        while (m := re.search(r"#figure\(", body)) is not None:
            try:
                _, end = balanced(body, m.end(), "(", ")")
            except ValueError:
                # An unclosed call swallows the rest of the file, as Typst would.
                body = body[: m.start()]
                break
            rest = TYPST_LABEL.sub("", body[end:], count=1)
            body = body[: m.start()] + " " + rest.removeprefix("\n")
    else:
        body = MD_FENCE.sub(" ", body)
    heading = HEADINGS[kind]
    titles: list[str] = [""]
    blocks: list[tuple[int, str]] = []
    current: list[str] = []

    def flush() -> None:
        if current:
            blocks.append((len(titles) - 1, " ".join(current)))
            current.clear()

    for line in body.splitlines():
        if h := heading.match(line):
            flush()
            titles.append(h.group("t").strip())
        elif line.strip():
            current.append(line.strip())
        else:
            flush()
    flush()
    return titles, blocks


def is_chained(sentence: str) -> bool:
    return CHAINED.search(INLINE_MATH.sub(" ", without_refs(sentence))) is not None


def nearest_rank(sorted_values: list[int], fraction: float) -> int:
    return sorted_values[max(math.ceil(fraction * len(sorted_values)) - 1, 0)]


def line_locator(text: str) -> Callable[[str], int]:
    """A function from successive sentences to their 1-based source lines."""
    cursor = 0
    line = 1

    def locate(sentence: str) -> int:
        nonlocal cursor, line
        head = sentence.split()[:4]
        pattern = r"\s+".join(re.escape(t) for t in head)
        if head and (m := re.compile(pattern).search(text, cursor)):
            line += text.count("\n", cursor, m.start())
            cursor = m.end()
        return line

    return locate


def sentence_stats(
    paragraphs: list[tuple[int, str, int]], text: str, kind: str, n_sections: int
) -> tuple[dict[str, Any], list[int]]:
    """Sentence metrics over all paragraphs, and the sentence count per section."""
    locate = line_locator(text)
    rows: list[tuple[int, int, str]] = []  # (words, line, text)
    per_section = [0] * n_sections
    for index, paragraph, _ in paragraphs:
        for sentence in SENTENCE_END.split(paragraph):
            if n := words(sentence, kind):
                rows.append((n, locate(sentence), sentence))
                per_section[index] += 1
    lengths = sorted(n for n, _, _ in rows)
    count = len(rows)
    long_count = sum(n > LONG_SENTENCE_WORDS for n in lengths)
    chained = sum(is_chained(t) for _, _, t in rows)
    longest = sorted(rows, key=lambda r: (-r[0], r[1]))[:LONGEST_SHOWN]
    return {
        "count": count,
        "median_words": statistics.median(lengths) if lengths else 0,
        "p90_words": nearest_rank(lengths, 0.9) if lengths else 0,
        "long_threshold_words": LONG_SENTENCE_WORDS,
        "over_long_threshold": long_count,
        "share_over_long_threshold": long_count / count if count else 0,
        "chained_count": chained,
        "chained_clause_rate": chained / count if count else 0,
        "longest": [{"words": n, "line": ln, "text": t} for n, ln, t in longest],
    }, per_section


def analyze(text: str, kind: str) -> dict[str, Any]:
    body = body_of(text, kind)
    titles, found = prose_blocks(body, kind)
    # A paragraph with no words is markup alone (`\maketitle`), not prose.
    paragraphs = [(i, p, n) for i, p in found if (n := words(p, kind))]
    counts = [n for _, _, n in paragraphs]
    sentences = [len(SENTENCE_END.split(p)) for _, p, _ in paragraphs]
    captions = captions_of(body, kind)
    caption_numbers: set[str] = set().union(*(numerics(c) for _, c in captions))
    body_numbers: set[str] = set().union(*(numerics(p) for _, p, _ in paragraphs))
    section_words = [0] * len(titles)
    for index, _, n in paragraphs:
        section_words[index] += n
    sentence_data, section_sentences = sentence_stats(
        paragraphs, text, kind, len(titles)
    )
    return {
        "paragraphs": {
            "count": len(counts),
            "median_words": statistics.median(counts) if counts else 0,
            "max_words": max(counts, default=0),
            "over_budget": sum(n > PARAGRAPH_BUDGET_WORDS for n in counts),
            "budget_words": PARAGRAPH_BUDGET_WORDS,
        },
        "sentences_per_paragraph": {
            "median": statistics.median(sentences) if sentences else 0,
            "max": max(sentences, default=0),
            "over_budget": sum(n > SENTENCE_BUDGET for n in sentences),
            "budget": SENTENCE_BUDGET,
        },
        "sentences": sentence_data,
        "captions": [
            {"label_or_index": label, "words": words(c, kind)} for label, c in captions
        ],
        "shared_numerics": sorted(caption_numbers & body_numbers),
        "sections": [
            {"title": t, "words": n, "sentences": k}
            for i, (t, n, k) in enumerate(
                zip(titles, section_words, section_sentences, strict=True)
            )
            if i > 0 or section_words[0]
        ],
    }


def format_report(data: dict[str, Any]) -> str:
    p, s = data["paragraphs"], data["sentences_per_paragraph"]
    t = data["sentences"]
    lines = [
        (
            f"paragraphs: {p['count']} (median {p['median_words']} words, "
            f"max {p['max_words']}, {p['over_budget']} over {p['budget_words']})"
        ),
        (
            f"sentences per paragraph: median {s['median']}, max {s['max']}, "
            f"{s['over_budget']} paragraphs over {s['budget']}"
        ),
        (
            f"sentences: {t['count']} (median {t['median_words']} words, "
            f"p90 {t['p90_words']}, {t['over_long_threshold']} over "
            f"{t['long_threshold_words']})"
        ),
        (
            f"chained-clause rate: {t['chained_clause_rate']:.2f} "
            f"({t['chained_count']} of {t['count']})"
        ),
        "longest sentences:",
        *(
            f"  line {x['line']}, {x['words']} words: {x['text'][:60]}"
            for x in t["longest"]
        ),
        "captions:",
        *(f"  {c['label_or_index']}: {c['words']} words" for c in data["captions"]),
        "shared caption/body numerics: "
        + (", ".join(data["shared_numerics"]) or "none"),
        "sections:",
        *(
            f"  {x['title'] or '(untitled)'}: {x['words']} words, "
            f"{x['sentences']} sentences"
            for x in data["sections"]
        ),
    ]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("path", help=".tex, .typ or .md file")
    parser.add_argument("--json", action="store_true", help="emit one JSON object")
    args = parser.parse_args(argv)
    path = Path(args.path)
    if path.suffix not in HEADINGS:
        print(f"{path}: unsupported suffix (want .tex, .typ or .md)", file=sys.stderr)
        return 2
    try:
        data = analyze(path.read_text(encoding="utf-8"), path.suffix)
    except (OSError, UnicodeDecodeError) as exc:
        print(f"{path}: cannot parse ({exc})", file=sys.stderr)
        return 1
    print(json.dumps(data, indent=2) if args.json else format_report(data))
    return 0


if __name__ == "__main__":
    sys.exit(main())

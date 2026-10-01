#!/usr/bin/env python
"""Report deterministic size metrics for scientific prose (LaTeX, Typst, Markdown).

Usage:
    python scripts/prose_metrics.py FILE [--json]

Reports paragraph and sentence budgets, caption lengths, numeric literals
shared between captions and body text, and words per section. It is a
report, not a gate: the exit code is 0 whenever the file parses.

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
- Numeric literals inside \\ref, \\label, \\cite or \\eqref arguments (and
  Typst ``@label`` references) are ignored, as are bare single digits 0-9:
  those are too common to signal that a caption repeats the body.
"""

from __future__ import annotations

import argparse
import json
import re
import statistics
import sys
from pathlib import Path
from typing import Any

PARAGRAPH_BUDGET_WORDS = 120
SENTENCE_BUDGET = 5

LATEX, TYPST, MARKDOWN = ".tex", ".typ", ".md"

# A "-" is a sign only when no digit, "-", "}" or ")" precedes it, so "3--5" is
# a range of 3 and 5 while "10^{-3}" keeps -3.
NUMERIC = re.compile(r"(?:(?<![\d\-})])-)?\d+(?:\.\d+)?(?:[eE]-?\d+)?")
SENTENCE_END = re.compile(r"(?<=[.?!])\s+(?=[A-Z\\])")
LATEX_REFS = re.compile(
    r"\\(?:ref|label|cite\w*|eqref|autoref|cref)\*?(?:\[[^\]]*\])?\{[^}]*\}"
)
TYPST_REFS = re.compile(r"@[\w:.-]+")
INLINE_MATH = re.compile(r"\$[^$]*\$|\\\(.*?\\\)")
LATEX_COMMAND = re.compile(r"\\[A-Za-z]+\*?(?:\[[^\]]*\])?")
TYPST_COMMAND = re.compile(r"#[A-Za-z][\w.]*")
LATEX_FLOATS = ("figure", "table")
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


LATEX_DROPPED = re.compile(
    latex_envs(LATEX_FLOATS + LATEX_DISPLAY_MATH) + r"|\\\[.*?\\\]|\$\$.*?\$\$",
    re.DOTALL,
)
TYPST_DISPLAY_MATH = re.compile(r"^[ \t]*\$[^$]*\$[ \t]*$", re.DOTALL | re.MULTILINE)
MD_FENCE = re.compile(r"^(```|~~~).*?^\1[ \t]*$", re.DOTALL | re.MULTILINE)
LATEX_ENV = re.compile(latex_envs(LATEX_FLOATS), re.DOTALL)
TYPST_LABEL = re.compile(r"^[ \t]*<[\w:.-]+>")
LATEX_LABEL = re.compile(r"\\label\{([^}]*)\}")
LATEX_COMMENT = re.compile(r"(?<!\\)%.*")
TYPST_COMMENT = re.compile(r"(?<!:)//.*")

HEADINGS = {
    LATEX: re.compile(r"\\(?:sub){0,2}section\*?(?:\[[^\]]*\])?\{(?P<t>[^}]*)\}"),
    TYPST: re.compile(r"^={1,2}\s+(?P<t>.*)$"),
    MARKDOWN: re.compile(r"^#{1,2}\s+(?P<t>.*)$"),
}


def balanced(text: str, start: int, opener: str, closer: str) -> tuple[str, int]:
    """The text inside a delimiter pair opened just before `start`, and its end.

    Raises ValueError when the pair never closes, which main reports as a parse
    failure rather than silently measuring a truncated caption.
    """
    depth = 1
    for i in range(start, len(text)):
        if text[i] == opener:
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


def captions_of(body: str, kind: str) -> list[tuple[int, str]]:
    """(offset, raw text) for every caption."""
    found: list[tuple[int, str]] = []
    if kind == LATEX:
        for m in re.finditer(r"\\caption\*?(?:\[[^\]]*\])?\{", body):
            inner, _ = balanced(body, m.end(), "{", "}")
            found.append((m.start(), inner))
    elif kind == TYPST:
        for m in re.finditer(r"caption:\s*\[", body):
            inner, _ = balanced(body, m.end(), "[", "]")
            found.append((m.start(), inner))
    return found


def caption_labels(body: str, kind: str) -> list[str | int]:
    """A label for each caption: the LaTeX \\label in its environment, else its index."""
    envs = [m.span() for m in LATEX_ENV.finditer(body)] if kind == LATEX else []
    labels: list[str | int] = []
    for index, (offset, _) in enumerate(captions_of(body, kind), start=1):
        label = None
        for lo, hi in envs:
            if lo <= offset < hi:
                m = LATEX_LABEL.search(body[lo:hi])
                label = m.group(1) if m else None
        labels.append(label if label is not None else index)
    return labels


def without_refs(text: str) -> str:
    return TYPST_REFS.sub(" ", LATEX_REFS.sub(" ", text))


def words(text: str, kind: str) -> int:
    text = INLINE_MATH.sub(" MATH ", without_refs(text))
    if kind == LATEX:
        text = LATEX_COMMAND.sub(" ", text).replace("{", " ").replace("}", " ")
        text = text.replace("~", " ")
    elif kind == TYPST:
        text = TYPST_COMMAND.sub(" ", text).replace("[", " ").replace("]", " ")
    return sum(1 for token in text.split() if re.search(r"\w", token))


def numerics(text: str) -> set[str]:
    return {
        n for n in NUMERIC.findall(without_refs(text)) if not re.fullmatch(r"\d", n)
    }


def prose_blocks(body: str, kind: str) -> tuple[list[str], list[tuple[str, str]]]:
    """Section titles, and (section title, paragraph text) for each paragraph."""
    if kind == LATEX:
        body = LATEX_DROPPED.sub("\n\n", body)
    elif kind == TYPST:
        body = TYPST_DISPLAY_MATH.sub("\n\n", body)
        while (m := re.search(r"#figure\(", body)) is not None:
            try:
                _, end = balanced(body, m.end(), "(", ")")
            except ValueError:
                # An unclosed call swallows the rest of the file, as Typst would.
                body = body[: m.start()]
                break
            rest = TYPST_LABEL.sub("", body[end:], count=1)
            body = body[: m.start()] + "\n\n" + rest
    else:
        body = MD_FENCE.sub("\n\n", body)
    heading = HEADINGS[kind]
    titles: list[str] = []
    blocks: list[tuple[str, str]] = []
    title = ""
    current: list[str] = []

    def flush() -> None:
        if current:
            blocks.append((title, " ".join(current)))
            current.clear()

    for line in body.splitlines():
        h = heading.search(line) if kind == LATEX else heading.match(line)
        if h:
            flush()
            title = h.group("t").strip()
            titles.append(title)
        elif line.strip():
            current.append(line.strip())
        else:
            flush()
    flush()
    return titles, blocks


def analyze(text: str, kind: str) -> dict[str, Any]:
    body = body_of(text, kind)
    titles, paragraphs = prose_blocks(body, kind)
    counts = [words(p, kind) for _, p in paragraphs]
    sentences = [len(SENTENCE_END.split(p)) for _, p in paragraphs]
    captions = [c for _, c in captions_of(body, kind)]
    caption_numbers: set[str] = set().union(*(numerics(c) for c in captions))
    body_numbers: set[str] = set().union(*(numerics(p) for _, p in paragraphs))
    section_words = dict.fromkeys(titles, 0)
    for (title, _), n in zip(paragraphs, counts, strict=True):
        section_words[title] = section_words.get(title, 0) + n
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
        "captions": [
            {"label_or_index": label, "words": words(c, kind)}
            for label, c in zip(caption_labels(body, kind), captions, strict=True)
        ],
        "shared_numerics": sorted(caption_numbers & body_numbers),
        "sections": [{"title": t, "words": n} for t, n in section_words.items()],
    }


def format_report(data: dict[str, Any]) -> str:
    p, s = data["paragraphs"], data["sentences_per_paragraph"]
    lines = [
        (
            f"paragraphs: {p['count']} (median {p['median_words']} words, "
            f"max {p['max_words']}, {p['over_budget']} over {p['budget_words']})"
        ),
        (
            f"sentences per paragraph: median {s['median']}, max {s['max']}, "
            f"{s['over_budget']} paragraphs over {s['budget']}"
        ),
        "captions:",
        *(f"  {c['label_or_index']}: {c['words']} words" for c in data["captions"]),
        "shared caption/body numerics: "
        + (", ".join(data["shared_numerics"]) or "none"),
        "sections:",
        *(
            f"  {x['title'] or '(untitled)'}: {x['words']} words"
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
    except (OSError, UnicodeDecodeError, ValueError) as exc:
        print(f"{path}: cannot parse ({exc})", file=sys.stderr)
        return 1
    print(json.dumps(data, indent=2) if args.json else format_report(data))
    return 0


if __name__ == "__main__":
    sys.exit(main())

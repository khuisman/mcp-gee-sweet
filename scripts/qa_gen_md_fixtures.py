#!/usr/bin/env python3
"""
Regenerate the generated Markdown-rendering fixtures and their expected-rendering
tables in docs/qa/tests/docs_markdown.md (#1044).

Usage:
    uv run python scripts/qa_gen_md_fixtures.py          # write
    uv run python scripts/qa_gen_md_fixtures.py --check  # exit 1 if anything is stale

Generated fixtures (under docs/qa/fixtures/md/syntax/): md-lists-nesting.md,
md-containment.md, md-adjacency-noblank.md, md-adjacency-blank.md,
md-inline-matrix.md, md-long-document.md, and docstart/*.md. Every other fixture
under docs/qa/fixtures/md/ is hand-written.

The suite file's matrix tables sit between `<!-- generated:<NAME> -->` and
`<!-- /generated:<NAME> -->` markers; only those spans are rewritten. Change an
expected rendering here, not in the suite file, or the next run reverts it.
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FIXTURES = ROOT / "docs" / "qa" / "fixtures" / "md"
SYNTAX = FIXTURES / "syntax"
SUITE = ROOT / "docs" / "qa" / "tests" / "docs_markdown.md"
IMG = "https://www.gstatic.com/images/branding/product/2x/docs_48dp.png"

# --- Nesting widths x list-type combinations (TC-MD106) ---------------------------

WIDTHS = [("2sp", "  "), ("3sp", "   "), ("4sp", "    "), ("tab", "\t")]
COMBOS = [
    ("bullet in bullet", "-", "-"),
    ("bullet in numbered", "1.", "-"),
    ("numbered in bullet", "-", "1."),
    ("numbered in numbered", "1.", "1."),
]


def _marker(kind: str, n: int) -> str:
    return f"{n}." if kind == "1." else "-"


def nesting() -> str:
    out = [
        "# Lists: nesting widths x type combinations",
        "",
        "Each case: three levels deep, then an item back at level 1, then an item back at",
        "level 0, so numbering continuation after a nested block is checked at both levels.",
        "Level 2 uses the same list type as level 0.",
        "",
    ]
    n = 0
    for wname, w in WIDTHS:
        for cname, p, c in COMBOS:
            n += 1
            out += [
                f"### LN-{n:02d} — {cname}, {wname}",
                "",
                f"{_marker(p, 1)} Top one",
                f"{w}{_marker(c, 1)} Child one",
                f"{w}{w}{_marker(p, 1)} Grandchild one",
                f"{w}{w}{_marker(p, 2)} Grandchild two",
                f"{w}{_marker(c, 2)} Child two",
                f"{_marker(p, 2)} Top two",
                f"{_marker(p, 3)} Top three",
                "",
            ]
    return "\n".join(out)


# --- Block constructs shared by the containment and adjacency matrices -------------

# id -> (label, source lines, what a reader sees)
BLOCKS = {
    "P": ("paragraph", ["Plain paragraph text."], 'a plain paragraph "Plain paragraph text."'),
    "H": ("heading", ["#### Inner heading"], 'a Heading 4 "Inner heading"'),
    "UL": (
        "bullet list",
        ["- Bullet A", "- Bullet B"],
        "a 2-item bullet list (Bullet A, Bullet B)",
    ),
    "OL": (
        "numbered list",
        ["1. Number A", "2. Number B"],
        "a 2-item numbered list (1. Number A, 2. Number B)",
    ),
    "TL": (
        "task list",
        ["- [ ] Task A", "- [x] Task B"],
        "a 2-item task list (☐ Task A, ☑ Task B)",
    ),
    "CB": ("code block", ["```", "code line", "```"], 'a monospace code block "code line"'),
    "BQ": ("blockquote", ["> Quoted line"], 'a quote (indent + left border) "Quoted line"'),
    "TB": (
        "table",
        ["| K | V |", "|---|---|", "| k1 | v1 |"],
        "a 2x2 table (bold header K/V, row k1/v1)",
    ),
    "IMG": ("image", [f"![pixel]({IMG})"], "an inline image on its own line"),
    "HR": ("rule", ["***"], "a horizontal rule"),
}

# What a contained block looks like; a contained list nests one level below its item.
CONTAINED = {
    **{k: v[2] for k, v in BLOCKS.items()},
    "UL": "a nested bullet list (Bullet A, Bullet B) one level deeper, with that level's glyph",
    "OL": "a nested numbered list (Number A, Number B) one level deeper, with that level's numbering style (C3)",
    "TL": "a nested task list (☐ Task A, ☑ Task B) one level deeper",
    "IMG": "the image",
}

# id, label, opener lines, indent for contained content, closer lines
CONTAINERS = [
    ("UL0", "bullet item, level 0", ["- Container item"], "    ", ["- Sibling after"]),
    (
        "UL1",
        "bullet item, level 1",
        ["- Top item", "    - Container item"],
        "        ",
        ["    - Sibling after", "- Top after"],
    ),
    (
        "UL2",
        "bullet item, level 2",
        ["- Top item", "    - Mid item", "        - Container item"],
        "            ",
        ["        - Sibling after", "    - Mid after", "- Top after"],
    ),
    ("OL0", "numbered item, level 0", ["1. Container item"], "    ", ["2. Sibling after"]),
    (
        "OL1",
        "numbered item, level 1",
        ["1. Top item", "    1. Container item"],
        "        ",
        ["    2. Sibling after", "2. Top after"],
    ),
    (
        "OL2",
        "numbered item, level 2",
        ["1. Top item", "    1. Mid item", "        1. Container item"],
        "            ",
        ["        2. Sibling after", "    2. Mid after", "2. Top after"],
    ),
    ("BQ1", "blockquote", ["> Container quote line", ">"], "> ", []),
    (
        "BQ2",
        "nested blockquote (depth 2)",
        ["> Outer quote", ">", "> > Container quote line", "> >"],
        "> > ",
        [],
    ),
]

CONTAINER_AFTER = {
    "UL0": 'then "Sibling after" as the next bullet at level 0, in the same list',
    "UL1": 'then "Sibling after" back at level 1 and "Top after" at level 0, all one list',
    "UL2": 'then "Sibling after" at level 2, "Mid after" at level 1, "Top after" at level 0, all one list',
    "OL0": 'then "Sibling after" numbered **2.** (numbering continues)',
    "OL1": 'then "Sibling after" numbered **b.** at level 1 and "Top after" numbered **2.** at level 0',
    "OL2": 'then "Sibling after" numbered **ii.** at level 2, "Mid after" **b.**, "Top after" **2.**',
    "BQ1": "all inside the quote (same left border and indent)",
    "BQ2": "all inside the inner quote (two levels of indent)",
}


def containment() -> tuple[str, list[str]]:
    lines = [
        "# Containment matrix: every block inside every container",
        "",
        "Contained content is indented 4 spaces per list level (valid in CommonMark and",
        "Python-Markdown alike), so a failure here is about containment, not indent width.",
        "",
    ]
    rows = []
    n = 0
    for cid, clabel, opener, ind, closer in CONTAINERS:
        for bid, (blabel, blines, _) in BLOCKS.items():
            n += 1
            case = f"CT-{n:02d}"
            lines += [f"### {case} — {blabel} inside {clabel}", ""]
            lines += opener
            if cid.startswith("BQ"):
                lines += [ind + b for b in blines]
            else:
                # Blank lines only where CommonMark needs one (a paragraph, table or
                # image line would otherwise join the item's text); elsewhere they'd
                # turn every case into a loose list, a separate variable (LB-02).
                gap = [""] if bid in ("P", "TB", "IMG") else []
                lines += gap + [ind + b for b in blines] + gap
            lines += [*closer, ""]
            first = '"Container item"' if not cid.startswith("BQ") else 'the "Container quote line"'
            where = (
                "indented under it as part of that item"
                if not cid.startswith("BQ")
                else "inside the quote"
            )
            rows.append(
                f"| {case} | {blabel} | {clabel} | {first}, then {CONTAINED[bid]} {where}, "
                f"{CONTAINER_AFTER[cid]} |"
            )
    return "\n".join(lines), rows


# Adjacency. "No blank line" expectations follow CommonMark 0.31 / GFM 0.29, plus D2.


def _nb_expect(a: str, b: str) -> str:
    sa, sb = BLOCKS[a][2], BLOCKS[b][2]
    two = f"{sa}, then {sb}"
    if b == "TB" and a in ("P", "IMG", "UL", "OL", "TL", "BQ"):
        return f"{two} (D2: the table starts its own block)"
    if a in ("P", "IMG"):
        if b == "P":
            return (
                'ONE paragraph: "Plain paragraph text." joined to what precedes it by a space'
                if a == "P"
                else 'ONE paragraph: the image, a space, then "Plain paragraph text."'
            )
        if b == "IMG":
            return (
                'ONE paragraph: "Plain paragraph text.", a space, then the image inline'
                if a == "P"
                else "ONE paragraph holding both images, separated by a space"
            )
        if b == "OL":
            return f"{two} (an ordered list starting at 1 may interrupt a paragraph)"
        return two
    if a in ("UL", "OL", "TL"):
        if b in ("P", "IMG"):
            return f"{sa}, with the next line joined to the last item's text by a space (lazy continuation)"
        if a == b or {a, b} == {"UL", "TL"}:
            return "ONE list holding all four items, in order" + (
                " (1. to 4.)" if a == "OL" else ""
            )
        return two
    if a == "BQ":
        if b in ("P", "IMG", "BQ"):
            return "ONE quote holding one paragraph: the next line joins the quoted line by a space"
        return two
    if a == "TB":
        if b in ("P", "IMG"):
            return (
                "the table with the next line as an extra one-cell body row "
                "(GFM: a table ends only at a blank line or another block)"
            )
        if b == "TB":
            return (
                "ONE table: the second table's three lines become body rows K/V, ---/---, k1/v1 "
                "(GFM: a table ends only at a blank line)"
            )
        return two
    return two  # H, CB and HR end at their own line


def _bl_expect(a: str, b: str) -> str:
    sa, sb = BLOCKS[a][2], BLOCKS[b][2]
    if (a == b and a in ("UL", "OL", "TL")) or {a, b} == {"UL", "TL"}:
        return (
            "ONE loose list holding all four items, in order (a blank line doesn't end a list)"
            + (" (1. to 4.)" if a == "OL" else "")
        )
    if a == b == "BQ":
        return "two separate quotes"
    return f"{sa}, then {sb}, as separate blocks"


def _second_block(a: str, b: str) -> list[str]:
    """Block b's lines, renamed when it would continue block a's list."""
    lines = list(BLOCKS[b][1])
    if a == b == "OL":
        return ["3. Number C", "4. Number D"]
    if a in ("UL", "TL") and b in ("UL", "TL"):
        return [line[:-1] + {"A": "C", "B": "D"}[line[-1]] for line in lines]
    return lines


def adjacency(blank: bool) -> tuple[str, list[str]]:
    prefix = "AB" if blank else "AJ"
    title = "with a blank line between" if blank else "with NO blank line between"
    lines = [f"# Adjacency matrix: block A directly followed by block B, {title}", ""]
    rows = []
    n = 0
    for a in BLOCKS:
        for b in BLOCKS:
            n += 1
            case = f"{prefix}-{n:03d}"
            lines += [f"### {case} — {BLOCKS[a][0]} then {BLOCKS[b][0]}", ""]
            lines += BLOCKS[a][1] + ([""] if blank else []) + _second_block(a, b) + [""]
            exp = _bl_expect(a, b) if blank else _nb_expect(a, b)
            rows.append(f"| {case} | {BLOCKS[a][0]} | {BLOCKS[b][0]} | {exp} |")
    return "\n".join(lines), rows


# --- Inline formatting matrix (TC-MD204) --------------------------------------------

STYLES = {
    "bold": ("**", "**", "bold"),
    "italic": ("*", "*", "italic"),
    "strike": ("~~", "~~", "struck through"),
    "code": ("`", "`", "monospace (Courier New)"),
    "link": ("[", "](https://example.com/inline)", "a link to https://example.com/inline"),
}
SAMPLE = "**B** *I* ~~S~~ `C` [L](https://example.com/inline)"
INLINE_CONTAINERS = [
    ("paragraph", lambda s: [s]),
    ("heading 2", lambda s: [f"## Heading {s}"]),
    ("heading 6", lambda s: [f"###### Heading {s}"]),
    ("bullet item, level 0", lambda s: [f"- Item {s}"]),
    ("bullet item, level 2", lambda s: ["- Top", "    - Mid", f"        - Item {s}"]),
    ("numbered item, level 0", lambda s: [f"1. Item {s}"]),
    ("numbered item, level 2", lambda s: ["1. Top", "    1. Mid", f"        1. Item {s}"]),
    ("task item", lambda s: [f"- [ ] Task {s}"]),
    ("table header cell", lambda s: [f"| Head {s} | H2 |", "|---|---|", "| a | b |"]),
    ("table body cell", lambda s: ["| H1 | H2 |", "|---|---|", f"| Cell {s} | b |"]),
    ("blockquote", lambda s: [f"> Quote {s}"]),
    ("nested blockquote", lambda s: ["> Outer", ">", f"> > Quote {s}"]),
]


def _wrap(style: str, text: str) -> str:
    o, c, _ = STYLES[style]
    return f"{o}{text}{c}"


def inline_matrix() -> tuple[str, list[str]]:
    lines = ["# Inline formatting matrix", ""]
    rows = []
    n = 0
    for outer in STYLES:
        for inner in STYLES:
            if outer == inner:
                continue
            n += 1
            case = f"IN-{n:02d}"
            if outer == "code":
                src = f"`{_wrap(inner, 'inner')} in code`"
                exp = (
                    f"the whole span `{_wrap(inner, 'inner')} in code` is monospace with the "
                    f"{inner} markers shown literally (no {inner} formatting inside code)"
                )
            else:
                src = _wrap(outer, f"outer {_wrap(inner, 'inner')} outer")
                exp = (
                    f'"outer inner outer" all {STYLES[outer][2]}; "inner" is also '
                    f"{STYLES[inner][2]}; no literal markers"
                )
            lines += [f"### {case} — {inner} inside {outer}", "", f"Before {src} after.", ""]
            rows.append(f"| {case} | {inner} inside {outer} | {exp} |")
    for name, build in INLINE_CONTAINERS:
        n += 1
        case = f"IN-{n:02d}"
        lines += [f"### {case} — every inline style inside a {name}", "", *build(SAMPLE), ""]
        rows.append(
            f"| {case} | all five styles in a {name} | B bold, I italic, S struck through, C monospace, "
            f"L a link; each style only on its own letter; the {name} itself renders correctly |"
        )
    return "\n".join(lines), rows


# --- Document boundaries (TC-MD301) and the long document (TC-MD302) ---------------

DOCSTART = {
    "ds-01-starts-bullets.md": "- First bullet is the first line of the doc\n- Second bullet\n",
    "ds-02-starts-numbered.md": "1. First numbered line of the doc\n2. Second\n",
    "ds-03-starts-table.md": "| Starts | With table |\n|---|---|\n| a | b |\n\nParagraph after the table.\n",
    "ds-04-starts-code.md": "```\ncode is the first line of the doc\n```\n\nParagraph after.\n",
    "ds-05-starts-quote.md": "> A quote is the first line of the doc\n\nParagraph after.\n",
    "ds-06-starts-image.md": f"![first]({IMG})\n\nParagraph after the image.\n",
    "ds-07-starts-rule.md": "***\n\nParagraph after a leading rule.\n",
    "ds-08-ends-table.md": "# Heading\n\nParagraph.\n\n| Ends | With table |\n|---|---|\n| a | b |\n",
    "ds-09-ends-list.md": "# Heading\n\n1. Ends with\n2. a numbered list\n",
    "ds-10-empty.md": "",
    "ds-11-whitespace-only.md": "\n\n   \n",
    "ds-12-no-trailing-newline.md": "No trailing newline at end of file",
    "ds-13-crlf-line-endings.md": "# CRLF heading\r\n\r\n- one\r\n- two\r\n\r\nParagraph.\r\n",
    "ds-14-front-matter.md": "---\ntitle: Front matter\nauthor: QA\n---\n\n# Body heading\n\nBody text.\n",
}


def long_document() -> str:
    parts = [
        "# Long document: all realistic fixtures, twice",
        "",
        "Generated by concatenating r01 to r16 twice, each preceded by a thematic break.",
        "",
    ]
    for rnd in (1, 2):
        for f in sorted((FIXTURES / "realistic").glob("r[0-9][0-9]-*.md")):
            parts += [
                "***",
                "",
                f"<!-- {f.name}, pass {rnd} -->",
                "",
                f.read_text(encoding="utf-8").rstrip("\n"),
                "",
            ]
    return "\n".join(parts)


# --- Driver --------------------------------------------------------------------------


def _table(header: str, rows: list[str]) -> str:
    return "\n".join([header, "|" + "---|" * header.count("|", 1), *rows])


def outputs() -> tuple[dict[Path, bytes], dict[str, str]]:
    files: dict[Path, bytes] = {}
    tables: dict[str, str] = {}
    files[SYNTAX / "md-lists-nesting.md"] = nesting().encode()
    text, rows = containment()
    files[SYNTAX / "md-containment.md"] = text.encode()
    tables["CT"] = _table("| Case | Block | Container | Expected |", rows)
    for blank, name in ((False, "noblank"), (True, "blank")):
        text, rows = adjacency(blank)
        files[SYNTAX / f"md-adjacency-{name}.md"] = text.encode()
        tables["AB" if blank else "AJ"] = _table("| Case | A | B | Expected |", rows)
    text, rows = inline_matrix()
    files[SYNTAX / "md-inline-matrix.md"] = text.encode()
    tables["IN"] = _table("| Case | Combination | Expected |", rows)
    files[SYNTAX / "md-long-document.md"] = long_document().encode()
    for name, body in DOCSTART.items():
        files[SYNTAX / "docstart" / name] = body.encode()
    return files, tables


def render_suite(suite: str, tables: dict[str, str]) -> str:
    for name, table in tables.items():
        start, end = f"<!-- generated:{name} -->", f"<!-- /generated:{name} -->"
        if suite.count(start) != 1 or suite.count(end) != 1:
            sys.exit(f"{SUITE.relative_to(ROOT)}: expected exactly one {start} … {end} span")
        head, rest = suite.split(start)
        _, tail = rest.split(end)
        suite = f"{head}{start}\n{table}\n{end}{tail}"
    return suite


def main() -> int:
    check = "--check" in sys.argv[1:]
    files, tables = outputs()
    files[SUITE] = render_suite(SUITE.read_text(encoding="utf-8"), tables).encode()
    stale = [p for p, data in files.items() if not p.exists() or p.read_bytes() != data]
    if check:
        for p in stale:
            print(f"stale: {p.relative_to(ROOT)}")
        return 1 if stale else 0
    for p in stale:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(files[p])
        print(f"wrote {p.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

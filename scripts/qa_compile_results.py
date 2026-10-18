"""Insert a release pass's per-TC results into docs/qa/tests/*.md.

Used by Aziz's compile step (aziz.md step 10): shard reports are collected into
one results spec, and this script writes every `**Result (date) STATUS**` entry
instead of hand-editing each test case.

Spec format (one entry per line; blank lines and `#` comments ignored):

    @<file.md> [default <STATUS> <note>]   # start a file section
    <TC-IDs> <STATUS> <note>               # one or more IDs, comma-separated

IDs may be ranges with a shared prefix: `TC-D217..TC-D232` or `TC-D217..D232`.
STATUS is PASS, FAIL, SKIP, or PARTIAL. A file-level default applies to every TC
in that file not listed explicitly; set one only when a shard reported running
the whole file. Any TC with neither an explicit entry nor a default gets a
`pending` entry and is printed, so nothing is ever recorded as run when it wasn't.

Each inserted entry carries a tag (default "v0.9.2 release pass"); a TC that
already has an entry with the same date and tag is skipped, so re-runs are safe.

Usage:
    uv run python scripts/qa_compile_results.py SPEC --date 2026-10-17 \
        --tag "v0.9.2 release pass" [--tests-dir docs/qa/tests] [--dry-run]
"""

import argparse
import re
import sys
from pathlib import Path

STATUS_LABEL = {
    "PASS": "✅ PASS",
    "FAIL": "❌ FAIL",
    "SKIP": "⏭️ SKIP",
    "PARTIAL": "🟡 PARTIAL",
}
HEADING_RE = re.compile(r"^### (TC-[A-Z]+\d+[a-z]?)\b")
ID_RE = re.compile(r"^(TC-[A-Z]+)(\d+)([a-z]?)$")


def expand_ids(token: str) -> list[str]:
    ids = []
    for part in token.split(","):
        part = part.strip()
        if ".." not in part:
            ids.append(part)
            continue
        start, end = part.split("..")
        m = ID_RE.match(start)
        if not m:
            raise ValueError(f"bad range start {start!r}")
        prefix, digits = m.group(1), m.group(2)
        end_num = re.sub(r"^(TC-)?[A-Z]+", "", end)
        # Keep the start's zero-padding: TC-D07..D09 means D07, D08, D09.
        ids.extend(f"{prefix}{n:0{len(digits)}d}" for n in range(int(digits), int(end_num) + 1))
    return ids


def parse_spec(path: Path) -> dict[str, dict]:
    files: dict[str, dict] = {}
    current = None
    for lineno, raw in enumerate(path.read_text().split("\n"), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("@"):
            parts = line[1:].split(maxsplit=3)
            current = files.setdefault(parts[0], {"default": None, "entries": {}})
            if len(parts) >= 3 and parts[1] == "default":
                current["default"] = (parts[2], parts[3] if len(parts) > 3 else "")
            continue
        if current is None:
            sys.exit(f"{path}:{lineno}: entry before any @file line")
        ids_token, status, *note = line.split(maxsplit=2)
        if status not in STATUS_LABEL:
            sys.exit(f"{path}:{lineno}: unknown status {status!r}")
        for tc in expand_ids(ids_token):
            current["entries"][tc] = (status, note[0] if note else "")
    return files


def section_bounds(lines: list[str]) -> list[tuple[str, int, int]]:
    """(TC id, heading index, index where its section ends) per heading.

    A list, not a dict: some files reuse an ID for two headings (e.g. two
    TC-W10 sections), and each heading needs its own entry.
    """
    heads = [(i, m.group(1)) for i, ln in enumerate(lines) if (m := HEADING_RE.match(ln))]
    bounds = []
    for n, (start, tc) in enumerate(heads):
        stop = heads[n + 1][0] if n + 1 < len(heads) else len(lines)
        for j in range(start + 1, stop):
            if lines[j].startswith("## "):
                stop = j
                break
        end = stop
        for j in range(start + 1, stop):
            if lines[j].strip() == "---":
                end = j
                break
        bounds.append((tc, start, end))
    return bounds


def compile_file(
    path: Path, spec: dict, date: str, tag: str, dry_run: bool
) -> tuple[int, list[str], list[str]]:
    # Split on "\n" only. str.splitlines() also breaks on \v, \f and other
    # separators, and some recorded results quote a literal \v (U+000B).
    text = path.read_text()
    lines = text[:-1].split("\n") if text.endswith("\n") else text.split("\n")
    bounds = section_bounds(lines)
    unknown = sorted(set(spec["entries"]) - {tc for tc, _, _ in bounds})
    pending = []
    inserts = []
    marker = f"**Result ({date}) "
    for tc, start, end in bounds:
        section = lines[start:end]
        if any(ln.startswith(marker) and tag in ln for ln in section):
            continue
        if tc in spec["entries"]:
            status, note = spec["entries"][tc]
        elif spec["default"]:
            status, note = spec["default"]
        else:
            pending.append(tc)
            status, note = None, "not reported by the shard that owned this file"
        label = STATUS_LABEL[status] if status else "⏳ pending"
        block = [f"{marker}{label} — {tag}**"]
        if note:
            block.append(note)
        insert_at = end
        while insert_at > start + 1 and lines[insert_at - 1].strip() == "":
            insert_at -= 1
        inserts.append((insert_at, ["", *block]))
    for at, block in sorted(inserts, reverse=True):
        lines[at:at] = block
    if not dry_run and inserts:
        path.write_text("\n".join(lines) + "\n")
    return len(inserts), pending, unknown


def main() -> None:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("spec", type=Path)
    ap.add_argument("--date", required=True)
    ap.add_argument("--tag", default="v0.9.2 release pass")
    ap.add_argument("--tests-dir", type=Path, default=Path("docs/qa/tests"))
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    files = parse_spec(args.spec)
    failed = False
    for name, spec in files.items():
        path = args.tests_dir / name
        if not path.exists():
            print(f"!! {name}: no such test file")
            failed = True
            continue
        count, pending, unknown = compile_file(path, spec, args.date, args.tag, args.dry_run)
        print(f"{name}: {count} entries {'would be ' if args.dry_run else ''}written")
        if pending:
            print(f"   pending (not reported): {', '.join(pending)}")
        if unknown:
            print(f"!! {name}: spec IDs with no matching heading: {', '.join(unknown)}")
            failed = True
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Fail when a NEW migrations/*.sql file lacks its expand_only declaration.

Copied from Muutto365/movingfirm-backend scripts/check_migration_declarations.py
(Ilari's decision 2026-10-20, MiraDesign answer 762c272f: "SQL files need a
declaration too"); keep the two in step. Every new migration file starts with one of

    -- expand_only: true
    -- expand_only: false

`true` only when `tyyni migration-safety --source sql_dir:migrations`
certifies the file; `false` for everything else (contract files included).
The broker's merge gate (ieepirzy/mirarun#183) refuses a migration-only PR
whose new SQL file does not declare `true`, and pairs the declaration with
Tyyni's own certification. This script checks the form only, so a mistake
shows up in CI before the gate sees it.

The form is the gate's, exactly (mirarun `migration_declaration.
read_sql_declaration`): one line that is exactly `-- expand_only: true` or
`-- expand_only: false` (key and value lowercase, only spaces or tabs
around them), in the file's leading comment block (blank lines and `--`
lines before the first statement; a `/* */` comment ends the block) and
within its first 20 lines. A BOM and CRLF line ends are fine. Any other
comment line starting with the key `expand_only`, a second declaration, or
one after the first statement is malformed. Prose such as
`-- Expand-only: new tables` is not a declaration.

Only files ADDED since the merge base with --base are checked: every
`.sql` file under `migrations/`, at any depth, as the gate reads its
`sql_dir:migrations` source (`db.py:apply_migrations()` runs only the
top-level ones, but the gate refuses an undeclared file anywhere under the
source, so this checks the same set). A rename counts as an addition under
its new name (`--no-renames`, as the gate's own diff); the gate sends every
rename or edit of an existing migration to a person anyway. The files that
existed before the decision carry no declaration and are never edited.

    python3 scripts/ci/check_migration_declarations.py --base origin/main

Stdlib only: the CI step needs no install.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys

NAME = "expand_only"
HEADER_LINES = 20
FORM = "`-- expand_only: true` (or false)"
_CANONICAL = re.compile(r"--[ \t]*expand_only:[ \t]*(true|false)[ \t]*")
_ATTEMPT = re.compile(r"[ \t]*--[ \t]*expand_only")


def read_declaration(source: str) -> tuple[bool | None, list[str]]:
    """(the declared value, or None when there is none; the problems).
    A file with problems declares nothing usable."""
    lines = [line.removesuffix("\r") for line in source.removeprefix("\ufeff").split("\n")]
    header_end = len(lines)
    for index, line in enumerate(lines):
        stripped = line.strip(" \t")
        if stripped and not stripped.startswith("--"):
            header_end = index
            break
    attempts = [(i, line) for i, line in enumerate(lines) if _ATTEMPT.match(line)]
    if not attempts:
        return None, []
    problems: list[str] = []
    if len(attempts) > 1:
        problems.append(
            f"{NAME} must be declared exactly once; found it on lines "
            + ", ".join(str(i + 1) for i, _ in attempts)
        )
    for index, line in attempts:
        if index >= header_end:
            problems.append(
                f"line {index + 1}: the {NAME} declaration comes after the first statement; "
                "it belongs in the leading comment block"
            )
        elif index >= HEADER_LINES:
            problems.append(
                f"line {index + 1}: the {NAME} declaration must be within the first {HEADER_LINES} lines"
            )
        elif not _CANONICAL.fullmatch(line):
            problems.append(f"line {index + 1}: write the declaration exactly as {FORM}")
    if problems:
        return None, problems
    match = _CANONICAL.fullmatch(attempts[0][1])
    assert match is not None
    return match.group(1) == "true", []


def check(source: str) -> list[str]:
    """What is wrong with a new migration file's declaration; empty if fine."""
    value, problems = read_declaration(source)
    if problems:
        return problems
    if value is None:
        return [f"no declaration: start the file with {FORM}"]
    return []


# The gate reads a file as raw bytes (`git cat-file blob`), decodes strict
# UTF-8 and refuses one it cannot read: over 1 MiB, not UTF-8, or a path
# with ":" (mirarun broker/inspection.py `read_text`). Read the same way.
# Never `text=True`: it turns a lone "\r" into a line break, so a file the
# gate reads as one malformed line would pass here.
MAX_BYTES = 1024 * 1024


def _git(*args: str) -> bytes:
    return subprocess.run(["git", *args], check=True, capture_output=True).stdout


def added_migrations(base: str) -> list[str]:
    merge_base = _git("merge-base", base, "HEAD").decode().strip()
    # -z: without it git C-quotes a name with non-ASCII bytes
    # ("migrations/058_p\303\244iv\303\244.sql"), which then fails the
    # `.sql` test and is silently skipped.
    out = _git(
        "diff", "--name-only", "-z", "--no-renames", "--no-ext-diff", "--diff-filter=A",
        merge_base, "HEAD", "--", "migrations/",
    )
    names = (n.decode("utf-8", "surrogateescape") for n in out.split(b"\0") if n)
    return sorted(n for n in names if n.startswith("migrations/") and n.endswith(".sql"))


def read_file(path: str) -> tuple[str | None, str | None]:
    """(the text, or None; why the gate could not read it)."""
    if path.startswith("-") or ":" in path:
        return None, 'the merge gate cannot read a path with ":"; rename the file'
    raw = _git("cat-file", "blob", f"HEAD:{path}")
    if len(raw) > MAX_BYTES:
        return None, "larger than 1 MiB, which the merge gate does not read"
    try:
        return raw.decode("utf-8"), None
    except UnicodeDecodeError:
        return None, "not UTF-8, which the merge gate does not read"


def _escape(value: str, *, prop: bool = False) -> str:
    """A GitHub workflow-command value: a file name must not end the
    command early or start a new one."""
    value = value.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")
    return value.replace(":", "%3A").replace(",", "%2C") if prop else value


def main(argv: list[str] | None = None) -> int:
    # `or ""`: under `python -OO` the docstring is gone and __doc__ is None.
    parser = argparse.ArgumentParser(description=(__doc__ or "").split("\n", 1)[0])
    parser.add_argument("--base", default="origin/main", help="compare HEAD with its merge base with this ref")
    args = parser.parse_args(argv)
    failures = 0
    paths = added_migrations(args.base)
    for path in paths:
        text, unreadable = read_file(path)
        problems = [unreadable] if unreadable else check(text or "")
        for problem in problems:
            print(f"::error file={_escape(path, prop=True)}::{_escape(f'{path}: {problem}')}")
        failures += bool(problems)
    print(f"{len(paths)} new migration file(s), {failures} without a valid {NAME} declaration")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())

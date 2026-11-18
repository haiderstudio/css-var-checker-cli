#!/usr/bin/env python3
"""Check CSS files for var(--name) references that resolve to
no --name defined anywhere in the checked files.

Run: python3 src/css_var_checker.py styles.css
     python3 src/css_var_checker.py project/
     python3 src/css_var_checker.py --stdin < styles.css

An undefined CSS variable fails silently: the property
falls back to whatever the variable's fallback value
says, or the declaration is dropped entirely, and the
layout breaks in a way that looks like an ordinary CSS
bug. The cause is usually a typo in a variable name,
or a variable that was renamed in the file where it is
defined but not where it is used. This tool names each
undefined reference, with the file and the line number,
and exits 1 when any is found, so it can fail a CI run.
A file with no undefined references exits 0.

A definition is a custom property declaration, a
--name followed by a colon inside a rule, for example
"--brand: blue;" inside ":root { ... }". A reference is
"var(--name)" anywhere in the CSS. A reference that
carries a fallback value, "var(--name, red)", counts
as defined: the author already handled the missing
case, so there is nothing to flag.

It reads CSS only. It never edits a file, never touches
the network, and reads only the files and folders you
point it at.
"""

import argparse
import fnmatch
import json
import os
import re
import sys
from pathlib import Path

__version__ = "1.0.0"

CSS_SUFFIX = ".css"

# A custom property name: two dashes, then letters, digits,
# underscores and dashes.
_NAME = r"--[A-Za-z0-9_-]+"
_REFERENCE = re.compile(r"var\(\s*(" + _NAME + r")")
_DEFINITION = re.compile(_NAME + r"\s*:")


def blank_comments_and_strings(text):
    """Blank comments and string contents, keeping positions.

    Returns (clean, unclosed_comment). clean is a copy of
    the text the same length, where every comment
    (/* ... */) and every quoted string has its contents
    replaced by spaces. Newlines are kept, so a line
    number measured in the blanked text is the line
    number in the original. Blanked text is safe to scan
    for var(--name) references: a var() inside a comment
    or a string (for example content: "var(--x)") is not
    a real reference. unclosed_comment is True when a "/*"
    never closes — the rest of the file is comment, so
    the blanked text blanks it to the end.
    """
    out = []
    unclosed = False
    i = 0
    size = len(text)
    while i < size:
        char = text[i]
        if char in ("\"", "'"):
            out.append(" ")
            i += 1
            while i < size and text[i] != char:
                if text[i] == "\\" and i + 1 < size:
                    out.append(" ")
                    out.append("\n" if text[i + 1] == "\n" else " ")
                    i += 2
                    continue
                out.append("\n" if text[i] == "\n" else " ")
                i += 1
            if i < size:
                out.append(" ")
                i += 1
        elif char == "/" and i + 1 < size and text[i + 1] == "*":
            end = text.find("*/", i + 2)
            if end == -1:
                unclosed = True
                for rest in text[i:]:
                    out.append("\n" if rest == "\n" else " ")
                i = size
            else:
                for rest in text[i:end + 2]:
                    out.append("\n" if rest == "\n" else " ")
                i = end + 2
        else:
            out.append(char)
            i += 1
    return "".join(out), unclosed


def _inside_block(clean, index):
    """True when index sits inside a rule block.

    A custom property definition only counts inside a
    rule: "--brand:" in a selector (for example
    ".a--brand:hover") is a class name, not a
    definition. Braces are counted in the blanked text,
    where comments and strings cannot hide or fake one.
    """
    depth = 0
    i = 0
    while i < index:
        if clean[i] == "{":
            depth += 1
        elif clean[i] == "}":
            depth -= 1
        i += 1
    return depth > 0


def collect_definitions(clean):
    """Every --name defined in one blanked document."""
    defined = set()
    for match in _DEFINITION.finditer(clean):
        if _inside_block(clean, match.start()):
            defined.add(match.group(0).split(":")[0].strip())
    return defined


def find_references(clean):
    """Every var(--name) reference in one blanked document.

    Returns a list of {"line": int, "name": str,
    "has_fallback": bool}, in document order. A reference
    has a fallback when a comma follows the name (after
    any spaces), as in var(--x, red).
    """
    references = []
    for match in _REFERENCE.finditer(clean):
        name = match.group(1)
        rest = clean[match.end():]
        stripped = rest.lstrip(" \t\r\n")
        has_fallback = stripped.startswith(",")
        line = clean.count("\n", 0, match.start()) + 1
        references.append({"line": line, "name": name,
                           "has_fallback": has_fallback})
    return references


def check_text(text, defined):
    """Check one document's text against known definitions.

    Returns (findings, errors). A finding is {"line": int,
    "name": str, "reason": str}, in document order. An
    error is a plain string, for a file that cannot be
    parsed at all (an unclosed comment) — it fails the
    check the same way a finding does.
    """
    findings = []
    errors = []
    clean, unclosed = blank_comments_and_strings(text)
    if unclosed:
        errors.append("unclosed comment — a \"/*\" never closes")
    for reference in find_references(clean):
        if reference["has_fallback"]:
            continue
        if reference["name"] not in defined:
            findings.append({
                "line": reference["line"],
                "name": reference["name"],
                "reason": ("is not defined — no %s definition "
                           "in the checked files"
                           % reference["name"]),
            })
    findings.sort(key=lambda item: item["line"])
    return findings, errors


def check_file(path):
    """Read one file. Returns (text, errors)."""
    try:
        text = Path(path).read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return None, ["not valid UTF-8"]
    except OSError as exc:
        return None, [str(exc)]
    return text, []


def collect_files(paths, recursive=True, exclude=None):
    """Expand CLI paths into a sorted list of CSS files.

    A file given directly is always checked, whatever its
    name. A folder is walked for files ending in .css
    only. .git folders are never walked, and directory
    links are never followed.
    """
    exclude = exclude or []
    found = []
    for raw in paths:
        path = Path(raw)
        if path.is_file():
            found.append(str(path))
        elif path.is_dir():
            for dirpath, dirs, files in os.walk(path, followlinks=False):
                dirs[:] = [
                    d for d in dirs
                    if d != ".git"
                    and not any(fnmatch.fnmatch(d, pat) for pat in exclude)
                ]
                for name in files:
                    if not name.endswith(CSS_SUFFIX):
                        continue
                    candidate = Path(dirpath) / name
                    if any(
                        fnmatch.fnmatch(str(candidate), pat)
                        or fnmatch.fnmatch(name, pat)
                        for pat in exclude
                    ):
                        continue
                    found.append(str(candidate))
                if not recursive:
                    break
        else:
            raise FileNotFoundError("no such file or folder: %s" % raw)
    seen = set()
    unique = []
    for item in found:
        if item not in seen:
            seen.add(item)
            unique.append(item)
    return sorted(unique)


def format_finding(path, finding):
    """One human-readable line for one undefined reference."""
    return ("FAIL %s: var(%s) line %d %s"
            % (path, finding["name"], finding["line"],
               finding["reason"]))


def run(paths, recursive=True, exclude=None, as_json=False):
    """Check paths, print the report, return the exit code.

    Definitions are collected from every file first, so
    a variable defined in one file satisfies a reference
    in another — a shared variables file is the normal
    case, and the check must not flag it.
    """
    try:
        files = collect_files(paths, recursive=recursive, exclude=exclude)
    except FileNotFoundError as exc:
        print("error: %s" % exc, file=sys.stderr)
        return 2
    if not files:
        print("error: no .css files found", file=sys.stderr)
        return 2
    texts = {}
    results = []
    defined = set()
    findings = 0
    files_with_findings = 0
    for path in files:
        text, errors = check_file(path)
        if text is None:
            findings += len(errors)
            files_with_findings += 1
            results.append({"path": path, "findings": [],
                            "errors": errors})
            continue
        texts[path] = text
        clean, _ = blank_comments_and_strings(text)
        defined |= collect_definitions(clean)
    for path in files:
        if path not in texts:
            continue
        bad, errors = check_text(texts[path], defined)
        count = len(bad) + len(errors)
        if count:
            findings += count
            files_with_findings += 1
        results.append({"path": path, "findings": bad,
                        "errors": errors})
    results.sort(key=lambda item: item["path"])
    if as_json:
        print(json.dumps(
            {"files": results, "checked": len(files),
             "findings": findings},
            indent=2))
    else:
        for result in results:
            for error in result["errors"]:
                print("FAIL %s: %s" % (result["path"], error))
            for finding in result["findings"]:
                print(format_finding(result["path"], finding))
        if findings:
            print("Checked %d file(s), %d undefined variable "
                  "reference(s) in %d file(s)."
                  % (len(files), findings, files_with_findings))
        else:
            print("OK — %d file(s) checked, no undefined "
                  "variable references." % len(files))
    return 1 if findings else 0


def run_stdin(as_json=False):
    """Check one CSS document read from standard input.

    Definitions come from the document itself: a variable
    defined and used in the same document passes.
    """
    text = sys.stdin.read()
    clean, _ = blank_comments_and_strings(text)
    defined = collect_definitions(clean)
    bad, errors = check_text(text, defined)
    findings = len(bad) + len(errors)
    if as_json:
        print(json.dumps(
            {"files": [{"path": "<stdin>", "findings": bad,
                        "errors": errors}],
             "checked": 1, "findings": findings},
            indent=2))
    else:
        for error in errors:
            print("FAIL <stdin>: %s" % error)
        for finding in bad:
            print(format_finding("<stdin>", finding))
        if findings:
            print("Checked 1 file(s), %d undefined variable "
                  "reference(s) in 1 file(s)." % findings)
        else:
            print("OK — 1 file(s) checked, no undefined "
                  "variable references.")
    return 1 if findings else 0


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="css_var_checker",
        description="Check CSS files for var(--name) references "
                    "with no --name defined in the checked files, "
                    "fail CI when one is found. Report-only — it "
                    "never edits a file.")
    parser.add_argument("paths", nargs="*",
                        help=".css files or folders to walk")
    parser.add_argument("--no-recursive", action="store_true",
                        help="do not walk into subfolders")
    parser.add_argument("--exclude", action="append", default=[],
                        help="skip files or folders matching this pattern "
                             "(repeatable)")
    parser.add_argument("--json", action="store_true",
                        help="print the result as JSON")
    parser.add_argument("--stdin", action="store_true",
                        help="check one CSS document from standard input")
    parser.add_argument("--version", action="version",
                        version="%(prog)s " + __version__)
    args = parser.parse_args(argv)
    if args.stdin:
        if args.paths:
            parser.error("--stdin takes no file or folder arguments")
        return run_stdin(as_json=args.json)
    if not args.paths:
        parser.error("give at least one .css file or folder")
    return run(args.paths, recursive=not args.no_recursive,
               exclude=args.exclude, as_json=args.json)


if __name__ == "__main__":
    sys.exit(main())

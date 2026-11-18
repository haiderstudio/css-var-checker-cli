# css-var-checker-cli

Check CSS files for var(--name) references that resolve to no --name defined in the project, fail CI when one is found.

[![CI](https://github.com/haiderstudio/css-var-checker-cli/actions/workflows/ci.yml/badge.svg)](https://github.com/haiderstudio/css-var-checker-cli/actions/workflows/ci.yml) [![Licence: MIT](https://img.shields.io/badge/Licence-MIT-yellow.svg)](LICENSE)

## What it does

`css_var_checker` reads CSS files, collects every
`--name` defined anywhere in the checked files, then
reports each `var(--name)` reference that resolves to
no definition — with the file and the line number. It
exits 1 when any undefined reference is found, so it
can fail a CI run. A project with no undefined
references exits 0.

- An undefined CSS variable fails silently: the
  property falls back to the fallback value, or the
  declaration is dropped, and the layout breaks in a
  way that looks like an ordinary CSS bug. The cause
  is usually a typo in a variable name, or a variable
  renamed where it is defined but not where it is
  used. A gate that names the exact line turns it
  into a one-word fix.
- Definitions are collected from every file first,
  so a variable defined in a shared variables file
  satisfies a reference in another file — that is the
  normal way projects use custom properties, and the
  check must not flag it.
- A reference with a fallback value,
  `var(--name, red)`, counts as defined: the author
  already handled the missing case, so there is
  nothing to flag.
- `var()` inside a comment or a string is not a real
  reference and is never flagged, and a `--name:`
  written inside a comment or a string is never
  counted as a definition. A class name that merely
  looks like a definition, for example
  `.a--brand:hover`, is not counted either — a
  definition only counts inside a rule block.
- A file given directly on the command line is always
  checked, whatever its name. A folder is walked for
  files ending in `.css` only, recursively by default
  (`--no-recursive` stops at the top level). `.git`
  folders are never walked, and directory links are
  never followed.
- `--json` prints the result as JSON, and `--stdin`
  checks one CSS document read from standard input.
- A file that cannot be parsed — an unclosed comment
  — is reported as an error and fails the check the
  same way a finding does.

## Who it is for

Anyone with a shared variables file — which is every
project that uses CSS custom properties. Undefined
variables pile up after renames, copy pastes, and
half-finished refactors, and no one notices them
because the page still renders, just wrongly. This is
the gate that names them at the pull request, before
they pile up further.

## What it does NOT do

- It does not check whether a variable is UNUSED.
  That is a different job — ekateriinal/
  css-variable-checker checks unused variables, not
  undefined references.
- It does not check whether a class is used in the
  HTML. That is repo #74, css-class-checker-cli,
  which checks UNUSED classes — an undefined variable
  reference is a different check on the same files.
- It does not check hex colours, empty rules, or
  duplicate properties. Those are repos #122,
  css-color-hex-checker-cli, #99,
  css-empty-rule-checker-cli, and #78,
  css-duplicate-property-checker-cli — different
  checks on the same files.
- It does not check what a variable's value is, or
  whether the value is valid for the property it is
  used on. It only checks that the name is defined
  somewhere in the checked files.
- It does not remove an undefined reference or
  rewrite the file. It reports, you fix the name.
- It never touches the network, and it only reads
  the files and folders you point it at.

## How this differs

- A fresh search of GitHub on Nov 16, 2026 found 0
  results for `"css-var-checker-cli"` and 3 results
  for `css var checker`. Two are not this job:
  ekateriinal/css-variable-checker (0 stars) checks
  UNUSED variables, and sonatype-nexus-community/
  undefined-css-variable-checker (1 star) is a
  JavaScript library plus a Chrome devtools extension,
  not a command-line gate. The third,
  VirtualExecutive/CSS-Undefined-Variable-Checker
  (0 stars, no description), was re-checked the same
  day: it has no README, no tests, and no CI — its
  root listing is Assets/Pages/Scripts/Styles plus a
  manifest.json, a browser-extension shape. No rival
  is a tested stdlib CLI with a CI exit code for
  undefined variable references in local CSS files.
- So the narrow slice stands: undefined references
  only, per-line reporting, a CI exit code, and a
  report-only tool that never edits a file.

## Install

```sh
git clone https://github.com/haiderstudio/css-var-checker-cli.git
cd css-var-checker-cli
```

There is nothing else to install: Python 3.10 or newer,
standard library only, no dependencies.

## Usage

Check one stylesheet:

```sh
python3 src/css_var_checker.py styles.css
```

A stylesheet with no undefined references passes:

```sh
$ python3 src/css_var_checker.py examples/clean.css
OK — 1 file(s) checked, no undefined variable references.
```

A stylesheet with undefined references fails, with
the variable name and line for each one:

```sh
$ python3 src/css_var_checker.py examples/flagged.css
FAIL examples/flagged.css: var(--missing) line 9 is not defined — no --missing definition in the checked files
FAIL examples/flagged.css: var(--typo) line 13 is not defined — no --typo definition in the checked files
Checked 1 file(s), 2 undefined variable reference(s) in 1 file(s).
```

Check a whole folder (`.css` files only) — a variable
defined in one file satisfies a reference in another:

```sh
$ python3 src/css_var_checker.py examples/
FAIL examples/flagged.css: var(--missing) line 9 is not defined — no --missing definition in the checked files
FAIL examples/flagged.css: var(--typo) line 13 is not defined — no --typo definition in the checked files
Checked 3 file(s), 2 undefined variable reference(s) in 1 file(s).
```

Check one document from standard input:

```sh
$ printf ':root {\n  --brand: blue;\n}\na {\n  color: var(--brand);\n  background: var(--gone);\n}\n' | python3 src/css_var_checker.py --stdin
FAIL <stdin>: var(--gone) line 6 is not defined — no --gone definition in the checked files
Checked 1 file(s), 1 undefined variable reference(s) in 1 file(s).
```

Machine-readable output:

```sh
$ python3 src/css_var_checker.py --json examples/flagged.css
{
  "files": [
    {
      "path": "examples/flagged.css",
      "findings": [
        {
          "line": 9,
          "name": "--missing",
          "reason": "is not defined \u2014 no --missing definition in the checked files"
        },
        {
          "line": 13,
          "name": "--typo",
          "reason": "is not defined \u2014 no --typo definition in the checked files"
        }
      ],
      "errors": []
    }
  ],
  "checked": 1,
  "findings": 2
}
```

Exit codes: 0 when no undefined reference is found, 1
when any undefined reference or parse error is found, 2
for a usage error (a missing path, a bad flag, or no
`.css` files found).

## Examples

A fallback counts as defined, and `var()` in a comment
or a string is not a reference — `examples/edge.css`
has both, and it passes:

```sh
$ python3 src/css_var_checker.py examples/edge.css
OK — 1 file(s) checked, no undefined variable references.
```

A variable defined in one file satisfies a reference
in another — that is the shared-variables-file case
the tool is built for:

```sh
$ printf ':root {\n  --brand: blue;\n}\n' > vars.css
$ printf 'a {\n  color: var(--brand);\n}\n' > use.css
$ python3 src/css_var_checker.py vars.css use.css
OK — 2 file(s) checked, no undefined variable references.
$ rm vars.css use.css
```

Run every bundled example at once with `sh
examples/run-example.sh` — the output is saved in
[examples/sample-output.md](examples/sample-output.md).

## How it is tested

```sh
python3 tests/test_css_var_checker.py
```

The tests cover undefined references (one undefined
reference, several in order, the same one twice,
nested var() without a fallback, a reference inside
`@media`, case-sensitive names), fallbacks (a plain
fallback, spaces around the comma, a nested var() as
the fallback), definitions (in the same rule, after
the use, with spaces around the colon, inside a media
block), lookalikes (a class name that looks like a
definition, `var()` in a comment or a string, a
definition written in a comment or a string), parse
errors (an unclosed comment, a non-UTF-8 file),
cross-file checks (a definition in another file
satisfying a reference, both files flagged), the CLI
(exit 0/1/2, folder walking for several CSS files,
nested folders, `--no-recursive`, `--exclude`, `.git`
skipped, a direct file checked whatever its name,
duplicate paths checked once, `--json` output,
`--stdin`, bad flags, missing paths, empty folders,
`--version`, input files left unchanged, the tool run
from `/` and under a fake HOME), the bundled examples
(sample output compared against a fresh run, and the
README-quoted outputs checked against it), and
hygiene checks (no placeholder text, no absolute
paths, no temp paths in any file, stdlib imports only,
no network use in the source, `.env` first in
`.gitignore`, CI file runs the test file, README names
the neighbouring repos).

## Contributing

Small, focused improvements are welcome — see [CONTRIBUTING.md](CONTRIBUTING.md).

## Licence

MIT — see [LICENSE](LICENSE).

## Original work

This tool was written from scratch for this repo. The
idea of checking a stylesheet is not new, and scanning
for `var(--name)` references is a standard technique —
but no existing tool does this one job, checking local
CSS files for undefined variable references as a
tested command-line gate, as the search above shows —
and every line of code here is original, built on
nothing but Python's standard library.

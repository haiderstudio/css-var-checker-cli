#!/usr/bin/env python3
"""Tests for css_var_checker — stdlib unittest only."""

import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout, redirect_stderr
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import css_var_checker as checker

REPO = Path(__file__).resolve().parent.parent


def run_cli(argv):
    """Run main(argv), capture stdout/stderr, return (code, out, err)."""
    out = io.StringIO()
    err = io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        try:
            code = checker.main(argv)
        except SystemExit as exc:
            code = exc.code
    return code, out.getvalue(), err.getvalue()


def write(tmp, name, text, encoding="utf-8"):
    path = Path(tmp) / name
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(text, bytes):
        path.write_bytes(text)
    else:
        path.write_text(text, encoding=encoding)
    return str(path)


def findings_of(text, defined=None):
    if defined is None:
        clean, _ = checker.blank_comments_and_strings(text)
        defined = checker.collect_definitions(clean)
    return checker.check_text(text, defined)


class TestUndefinedReferences(unittest.TestCase):
    def test_clean_file_passes(self):
        bad, errors = findings_of(
            ":root {\n  --brand: blue;\n}\n"
            "body {\n  color: var(--brand);\n}\n")
        self.assertEqual(bad, [])
        self.assertEqual(errors, [])

    def test_undefined_reference_flagged(self):
        bad, _ = findings_of("body {\n  color: var(--missing);\n}\n")
        self.assertEqual(len(bad), 1)
        self.assertEqual(bad[0]["line"], 2)
        self.assertEqual(bad[0]["name"], "--missing")
        self.assertIn("not defined", bad[0]["reason"])

    def test_several_undefined_in_order(self):
        bad, _ = findings_of(
            "a {\n  color: var(--one);\n  background: var(--two);\n}\n")
        self.assertEqual([item["name"] for item in bad],
                         ["--one", "--two"])
        self.assertEqual([item["line"] for item in bad], [2, 3])

    def test_same_undefined_twice_reported_twice(self):
        bad, _ = findings_of(
            "a {\n  color: var(--x);\n}\n"
            "b {\n  color: var(--x);\n}\n")
        self.assertEqual(len(bad), 2)
        self.assertEqual([item["line"] for item in bad], [2, 5])

    def test_fallback_counts_as_defined(self):
        bad, _ = findings_of("a {\n  color: var(--x, red);\n}\n")
        self.assertEqual(bad, [])

    def test_fallback_with_spaces_counts(self):
        bad, _ = findings_of("a {\n  color: var(--x , red);\n}\n")
        self.assertEqual(bad, [])

    def test_fallback_with_nested_var_counts(self):
        bad, _ = findings_of(
            "a {\n  color: var(--x, var(--y, blue));\n}\n")
        self.assertEqual(bad, [])

    def test_nested_var_without_fallback_flagged(self):
        bad, _ = findings_of("a {\n  color: var(--x, var(--y));\n}\n")
        self.assertEqual([item["name"] for item in bad], ["--y"])

    def test_definition_in_same_rule_passes(self):
        bad, _ = findings_of(
            ".card {\n  --pad: 1rem;\n  padding: var(--pad);\n}\n")
        self.assertEqual(bad, [])

    def test_definition_after_use_passes(self):
        bad, _ = findings_of(
            "a {\n  color: var(--late);\n}\n"
            ":root {\n  --late: red;\n}\n")
        self.assertEqual(bad, [])

    def test_definition_with_spaces_around_colon(self):
        bad, _ = findings_of(
            ":root {\n  --spaced : blue;\n}\n"
            "a {\n  color: var(--spaced);\n}\n")
        self.assertEqual(bad, [])

    def test_definition_in_media_block_passes(self):
        bad, _ = findings_of(
            "@media (min-width: 600px) {\n"
            "  :root {\n    --wide: 1rem;\n  }\n}\n"
            "a {\n  padding: var(--wide);\n}\n")
        self.assertEqual(bad, [])

    def test_reference_inside_media_flagged(self):
        bad, _ = findings_of(
            "@media (min-width: 600px) {\n"
            "  a {\n    color: var(--gone);\n  }\n}\n")
        self.assertEqual(len(bad), 1)
        self.assertEqual(bad[0]["line"], 3)

    def test_name_with_digits_dashes_underscores(self):
        bad, _ = findings_of(
            ":root {\n  --brand-2_x: blue;\n}\n"
            "a {\n  color: var(--brand-2_x);\n  border-color: var(--brand-2_y);\n}\n")
        self.assertEqual([item["name"] for item in bad], ["--brand-2_y"])

    def test_case_sensitive_names(self):
        bad, _ = findings_of(
            ":root {\n  --Brand: blue;\n}\n"
            "a {\n  color: var(--brand);\n}\n")
        self.assertEqual(len(bad), 1)
        self.assertEqual(bad[0]["name"], "--brand")

    def test_selector_that_looks_like_definition(self):
        bad, _ = findings_of(
            ".a--brand:hover {\n  color: var(--brand);\n}\n")
        self.assertEqual(len(bad), 1)
        self.assertEqual(bad[0]["name"], "--brand")

    def test_var_in_comment_not_flagged(self):
        bad, _ = findings_of(
            "/* var(--ghost) */\n"
            "a {\n  color: red;\n}\n")
        self.assertEqual(bad, [])

    def test_var_in_string_not_flagged(self):
        bad, _ = findings_of(
            'a::before {\n  content: "var(--ghost)";\n}\n')
        self.assertEqual(bad, [])

    def test_var_in_comment_after_rule_not_flagged(self):
        bad, _ = findings_of(
            "a {\n  color: red; /* var(--ghost) */\n}\n")
        self.assertEqual(bad, [])

    def test_definition_in_comment_not_counted(self):
        bad, _ = findings_of(
            "/* --ghost: red; */\n"
            "a {\n  color: var(--ghost);\n}\n")
        self.assertEqual(len(bad), 1)

    def test_definition_in_string_not_counted(self):
        bad, _ = findings_of(
            'a::before {\n  content: "--ghost: red";\n}\n'
            "b {\n  color: var(--ghost);\n}\n")
        self.assertEqual(len(bad), 1)

    def test_empty_document_passes(self):
        bad, errors = findings_of("")
        self.assertEqual(bad, [])
        self.assertEqual(errors, [])

    def test_comment_only_document_passes(self):
        bad, errors = findings_of("/* nothing here */\n")
        self.assertEqual(bad, [])
        self.assertEqual(errors, [])

    def test_unclosed_comment_is_error(self):
        bad, errors = findings_of(
            "/* never closes\n"
            "a {\n  color: var(--x);\n}\n")
        self.assertEqual(bad, [])
        self.assertEqual(len(errors), 1)
        self.assertIn("unclosed comment", errors[0])

    def test_var_with_no_name_is_not_a_reference(self):
        bad, _ = findings_of("a {\n  color: var(red);\n}\n")
        self.assertEqual(bad, [])


class TestCrossFile(unittest.TestCase):
    def test_definition_in_another_file_satisfies(self):
        with tempfile.TemporaryDirectory() as tmp:
            write(tmp, "vars.css",
                  ":root {\n  --brand: blue;\n}\n")
            use = write(tmp, "use.css",
                        "a {\n  color: var(--brand);\n}\n")
            code, out, _ = run_cli([tmp])
            self.assertEqual(code, 0)
            self.assertIn("no undefined", out)
            self.assertNotIn(use, out)

    def test_undefined_in_second_file_flagged(self):
        with tempfile.TemporaryDirectory() as tmp:
            write(tmp, "vars.css",
                  ":root {\n  --brand: blue;\n}\n")
            write(tmp, "use.css",
                  "a {\n  color: var(--brand);\n"
                  "  background: var(--gone);\n}\n")
            code, out, _ = run_cli([tmp])
            self.assertEqual(code, 1)
            self.assertIn("var(--gone) line 3", out)
            self.assertNotIn("--brand) line", out)

    def test_two_files_both_flagged(self):
        with tempfile.TemporaryDirectory() as tmp:
            write(tmp, "a.css", "a {\n  color: var(--x);\n}\n")
            write(tmp, "b.css", "b {\n  color: var(--y);\n}\n")
            code, out, _ = run_cli([tmp])
            self.assertEqual(code, 1)
            self.assertIn("var(--x) line 2", out)
            self.assertIn("var(--y) line 2", out)
            self.assertIn("2 undefined variable reference(s) in 2 file(s)",
                          out)


class TestCli(unittest.TestCase):
    def test_clean_file_exit_zero(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = write(tmp, "ok.css",
                         "a {\n  color: red;\n}\n")
            code, out, _ = run_cli([path])
            self.assertEqual(code, 0)
            self.assertIn("OK", out)

    def test_flagged_file_exit_one(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = write(tmp, "bad.css",
                         ".x {\n  color: var(--nope);\n}\n")
            code, out, _ = run_cli([path])
            self.assertEqual(code, 1)
            self.assertIn("FAIL %s: var(--nope) line 2" % path, out)
            self.assertIn("1 undefined variable reference(s)", out)

    def test_folder_walk(self):
        with tempfile.TemporaryDirectory() as tmp:
            write(tmp, "a.css", "a {\n  color: red;\n}\n")
            write(tmp, "b.css", ".x {\n  color: var(--nope);\n}\n")
            write(tmp, "notes.txt", ".y {\n  color: var(--nope);\n}\n")
            code, out, _ = run_cli([tmp])
            self.assertEqual(code, 1)
            self.assertIn("Checked 2 file(s)", out)

    def test_nested_folders(self):
        with tempfile.TemporaryDirectory() as tmp:
            write(tmp, "sub/deep.css",
                  ".x {\n  color: var(--nope);\n}\n")
            code, out, _ = run_cli([tmp])
            self.assertEqual(code, 1)
            self.assertIn("var(--nope)", out)

    def test_no_recursive(self):
        with tempfile.TemporaryDirectory() as tmp:
            write(tmp, "top.css", "a {\n  color: red;\n}\n")
            write(tmp, "sub/deep.css",
                  ".x {\n  color: var(--nope);\n}\n")
            code, out, _ = run_cli(["--no-recursive", tmp])
            self.assertEqual(code, 0)
            self.assertIn("1 file(s) checked", out)

    def test_exclude(self):
        with tempfile.TemporaryDirectory() as tmp:
            write(tmp, "a.css", ".x {\n  color: var(--nope);\n}\n")
            write(tmp, "skip.css", ".y {\n  color: var(--nope);\n}\n")
            code, out, _ = run_cli(["--exclude", "skip.css", tmp])
            self.assertEqual(code, 1)
            self.assertIn("Checked 1 file(s)", out)

    def test_git_folder_skipped(self):
        with tempfile.TemporaryDirectory() as tmp:
            write(tmp, ".git/hooks/bad.css",
                  ".x {\n  color: var(--nope);\n}\n")
            write(tmp, "a.css", "a {\n  color: red;\n}\n")
            code, out, _ = run_cli([tmp])
            self.assertEqual(code, 0)
            self.assertIn("1 file(s) checked", out)

    def test_direct_file_checked_whatever_its_name(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = write(tmp, "style.txt",
                         ".x {\n  color: var(--nope);\n}\n")
            code, out, _ = run_cli([path])
            self.assertEqual(code, 1)
            self.assertIn("var(--nope)", out)

    def test_duplicate_paths_checked_once(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = write(tmp, "a.css",
                         ".x {\n  color: var(--nope);\n}\n")
            code, out, _ = run_cli([path, path])
            self.assertEqual(code, 1)
            self.assertIn("Checked 1 file(s)", out)

    def test_json_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = write(tmp, "bad.css",
                         ".x {\n  color: var(--nope);\n}\n")
            code, out, _ = run_cli(["--json", path])
            self.assertEqual(code, 1)
            data = json.loads(out)
            self.assertEqual(data["checked"], 1)
            self.assertEqual(data["findings"], 1)
            self.assertEqual(data["files"][0]["findings"][0]["name"],
                             "--nope")
            self.assertEqual(data["files"][0]["findings"][0]["line"], 2)

    def test_stdin(self):
        with tempfile.TemporaryDirectory() as tmp:
            old_stdin = sys.stdin
            sys.stdin = io.StringIO(
                ":root {\n  --ok: red;\n}\n"
                "a {\n  color: var(--ok);\n  background: var(--nope);\n}\n")
            try:
                code, out, _ = run_cli(["--stdin"])
            finally:
                sys.stdin = old_stdin
            self.assertEqual(code, 1)
            self.assertIn("FAIL <stdin>: var(--nope) line 6", out)

    def test_stdin_clean(self):
        old_stdin = sys.stdin
        sys.stdin = io.StringIO("a {\n  color: red;\n}\n")
        try:
            code, out, _ = run_cli(["--stdin"])
        finally:
            sys.stdin = old_stdin
        self.assertEqual(code, 0)
        self.assertIn("no undefined", out)

    def test_bad_flags(self):
        code, _, err = run_cli(["--no-such-flag"])
        self.assertEqual(code, 2)
        self.assertIn("unrecognized arguments", err)

    def test_missing_path(self):
        code, _, err = run_cli(["no-such-file.css"])
        self.assertEqual(code, 2)
        self.assertIn("no such file or folder", err)

    def test_empty_folder(self):
        with tempfile.TemporaryDirectory() as tmp:
            code, _, err = run_cli([tmp])
            self.assertEqual(code, 2)
            self.assertIn("no .css files found", err)

    def test_no_paths(self):
        code, _, err = run_cli([])
        self.assertEqual(code, 2)
        self.assertIn("give at least one", err)

    def test_stdin_with_paths_rejected(self):
        code, _, err = run_cli(["--stdin", "a.css"])
        self.assertEqual(code, 2)
        self.assertIn("--stdin takes no file", err)

    def test_version(self):
        code, out, _ = run_cli(["--version"])
        self.assertEqual(code, 0)
        self.assertIn("css_var_checker 1.0.0", out)

    def test_non_utf8_file_reported(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = write(tmp, "bad.css", b"\xff\xfe\x00bad")
            code, out, _ = run_cli([path])
            self.assertEqual(code, 1)
            self.assertIn("not valid UTF-8", out)

    def test_input_files_left_unchanged(self):
        with tempfile.TemporaryDirectory() as tmp:
            text = ".x {\n  color: var(--nope);\n}\n"
            path = write(tmp, "a.css", text)
            run_cli([path])
            self.assertEqual(Path(path).read_text(), text)

    def test_run_from_root_and_fake_home(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = write(tmp, "a.css", "a {\n  color: red;\n}\n")
            env = dict(os.environ)
            env["HOME"] = tmp
            result = subprocess.run(
                [sys.executable,
                 str(REPO / "src" / "css_var_checker.py"), path],
                capture_output=True, text=True, cwd="/", env=env)
            self.assertEqual(result.returncode, 0)
            self.assertIn("no undefined", result.stdout)


class TestExamples(unittest.TestCase):
    def test_run_example_output_matches_sample(self):
        sample = (REPO / "examples" / "sample-output.md").read_text()
        result = subprocess.run(
            ["sh", str(REPO / "examples" / "run-example.sh")],
            capture_output=True, text=True, cwd=str(REPO))
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout.strip(), sample.strip())

    def test_readme_quotes_match_real_runs(self):
        readme = (REPO / "README.md").read_text()
        flagged = (REPO / "examples" / "flagged.css").read_text()
        clean, _ = checker.blank_comments_and_strings(flagged)
        defined = checker.collect_definitions(clean)
        bad, _ = checker.check_text(flagged, defined)
        for item in bad:
            line = ("FAIL examples/flagged.css: var(%s) line %d %s"
                    % (item["name"], item["line"], item["reason"]))
            self.assertIn(line, readme)

    def test_clean_example_passes(self):
        code, _, _ = run_cli([str(REPO / "examples" / "clean.css")])
        self.assertEqual(code, 0)

    def test_flagged_example_fails_with_two(self):
        flagged = (REPO / "examples" / "flagged.css").read_text()
        clean, _ = checker.blank_comments_and_strings(flagged)
        defined = checker.collect_definitions(clean)
        bad, _ = checker.check_text(flagged, defined)
        self.assertEqual(len(bad), 2)
        self.assertEqual([item["name"] for item in bad],
                         ["--missing", "--typo"])

    def test_edge_example_passes(self):
        code, _, _ = run_cli([str(REPO / "examples" / "edge.css")])
        self.assertEqual(code, 0)


class TestHygiene(unittest.TestCase):
    def _repo_files(self, skip_tests=True):
        """Every file in the repo, minus .git and caches."""
        for path in REPO.rglob("*"):
            if path.is_dir():
                continue
            if ".git" in path.parts or "__pycache__" in path.parts:
                continue
            if path.suffix == ".pyc":
                continue
            if skip_tests and "tests" in path.parts:
                continue
            yield path

    def test_no_placeholder_text(self):
        banned = ["TODO", "coming soon", "lorem", "FIXME", "XXX"]
        hits = []
        for path in self._repo_files(skip_tests=True):
            text = path.read_text(errors="ignore")
            for word in banned:
                if word in text:
                    hits.append("%s: %s" % (path.name, word))
        self.assertEqual(hits, [])

    def test_no_absolute_paths(self):
        hits = []
        for path in self._repo_files(skip_tests=True):
            text = path.read_text(errors="ignore")
            for marker in ("/home/", "/Users/", "C:\\"):
                if marker in text:
                    hits.append("%s: %s" % (path.name, marker))
        self.assertEqual(hits, [])

    def test_no_temp_paths_in_files(self):
        hits = []
        for path in self._repo_files(skip_tests=False):
            text = path.read_text(errors="ignore")
            if "/t" + "mp/" in text:
                hits.append(str(path))
        self.assertEqual(hits, [])

    def test_stdlib_imports_only(self):
        import ast
        stdlib = set(sys.stdlib_module_names)
        for target in (REPO / "src" / "css_var_checker.py",
                       REPO / "tests" / "test_css_var_checker.py"):
            tree = ast.parse(target.read_text())
            imported = set()
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    imported.update(a.name.split(".")[0]
                                    for a in node.names)
                elif isinstance(node, ast.ImportFrom) and node.module:
                    imported.add(node.module.split(".")[0])
            self.assertFalse(
                imported - stdlib - {"css_var_checker"},
                (target.name, imported))
            self.assertNotIn("yaml", imported)

    def test_no_network_use_in_src(self):
        src = (REPO / "src" / "css_var_checker.py").read_text()
        for marker in ("urllib.request", "requests", "socket",
                       "http.client", "urlopen", "urlretrieve"):
            self.assertNotIn(marker, src, marker)

    def test_gitignore_lists_env_first(self):
        lines = (REPO / ".gitignore").read_text().splitlines()
        self.assertTrue(lines, ".gitignore is empty")
        self.assertEqual(lines[0], ".env")

    def test_ci_runs_this_test_file(self):
        ci = (REPO / ".github" / "workflows" / "ci.yml").read_text()
        self.assertIn("tests/test_css_var_checker.py", ci)
        self.assertIn("ubuntu-latest", ci)
        self.assertIn("3.12", ci)
        self.assertIn("actions/checkout", ci)
        self.assertIn("setup-python", ci)
        self.assertIn("push", ci)
        self.assertIn("pull_request", ci)

    def test_readme_names_the_neighbouring_repos(self):
        readme = (REPO / "README.md").read_text()
        for name in ("css-class-checker-cli",
                     "css-duplicate-property-checker-cli",
                     "css-empty-rule-checker-cli"):
            self.assertIn(name, readme)


if __name__ == "__main__":
    unittest.main(verbosity=2)

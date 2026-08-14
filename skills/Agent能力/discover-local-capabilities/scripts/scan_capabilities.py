#!/usr/bin/env python3
"""Compatibility wrapper for the v2 capability-map scanner."""

from __future__ import annotations

import argparse
import contextlib
import os
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import TextIO

import capability_map


def load_rules(_skill_dir: Path) -> list[dict[str, object]]:
    """The v2 classifier intentionally has no author-specific routing rules."""

    return []


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Generate a local capability map using the v2 workflow."
    )
    parser.add_argument("--project", default=".")
    parser.add_argument("--output-dir", default=".capability-map")
    parser.add_argument("--skill-root", action="append", default=[])
    parser.add_argument("--cli", action="append", default=[])
    parser.add_argument("--probe-versions", action="store_true")
    return parser


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    """Parse the legacy argument surface for import-compatible callers."""

    return _parser().parse_args(None if argv is None else list(argv))


def main(
    argv: Sequence[str] | None = None,
    *,
    environ: Mapping[str, str] | None = None,
    home: Path | None = None,
    cwd: Path | None = None,
    stdout: TextIO | None = None,
    stderr: TextIO | None = None,
) -> int:
    """Translate legacy scan arguments into a confirmed v2 scan write."""

    output = sys.stdout if stdout is None else stdout
    errors = sys.stderr if stderr is None else stderr
    with contextlib.redirect_stdout(output), contextlib.redirect_stderr(errors):
        try:
            args = parse_args(argv)
        except SystemExit as error:
            return int(error.code)
    runtime_cwd = Path.cwd() if cwd is None else Path(cwd).absolute()
    injected_home = Path.home() if home is None else Path(home).absolute()

    def absolute(value: str, base: Path) -> Path:
        if value == "~":
            return injected_home
        if value.startswith(("~/", "~\\")):
            return (injected_home / value[2:]).absolute()
        path = Path(value)
        return path.absolute() if path.is_absolute() else (base / path).absolute()

    project = absolute(args.project, runtime_cwd)
    output_directory = absolute(args.output_dir, project)
    translated = [
        "scan",
        "--project",
        os.fspath(project),
        "--output-dir",
        os.fspath(output_directory),
        "--confirmed",
    ]
    for root in args.skill_root:
        translated.extend(("--skill-root", root))
    if args.probe_versions:
        translated.extend(("--probe-versions", "explicit"))
    if args.cli:
        errors.write(
            "warning: --cli is deprecated; v2 scans every executable in PATH.\n"
        )
    return capability_map.main(
        translated,
        environ=environ,
        home=home,
        cwd=cwd,
        stdout=output,
        stderr=errors,
    )


if __name__ == "__main__":
    raise SystemExit(main())

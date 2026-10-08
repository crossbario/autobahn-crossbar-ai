###############################################################################
#
#  Copyright (C) typedef int GmbH
#  SPDX-License-Identifier: MIT
#
###############################################################################
"""Fixtures: Python-package repositories built in a temp dir, and the scripts.

The aspect scripts are standalone (run by path, ``from _pp import ...``), so the tests
import them the same way - with their directory on ``sys.path`` - and also run them as
the engine does, as subprocesses.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).parents[1] / "aspects" / "python-package" / "scripts"
sys.path.insert(0, str(SCRIPTS))

GOOD_PYPROJECT = """\
[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[project]
name = "pkg"
version = "26.10.1"
requires-python = ">=3.11"
license = "MIT"
"""


def make_package(root: Path, name: str = "pkg", **overrides: str | None) -> Path:
    """A package repo: ``pyproject.toml`` + ``src/<name>/``; ``None`` drops a file."""
    repo = root / name
    files: dict[str, str | None] = {
        "pyproject.toml": GOOD_PYPROJECT,
        f"src/{name}/__init__.py": '"""Pkg."""\n',
        f"src/{name}/core.py": "X = 1\n",
    }
    files.update(overrides)
    for rel, text in files.items():
        if text is None:
            continue
        path = repo / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    return repo


@pytest.fixture
def package(tmp_path):
    """Factory: ``package(name="pkg", **{relpath: text_or_None})``."""
    return lambda name="pkg", **overrides: make_package(tmp_path, name, **overrides)


def run_script(name: str, *args: str) -> subprocess.CompletedProcess:
    """Run an aspect script by path, as the engine does."""
    return subprocess.run(
        [sys.executable, str(SCRIPTS / name), *args],
        capture_output=True,
        text=True,
        check=False,
    )

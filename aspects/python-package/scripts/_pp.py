###############################################################################
#
#  Copyright (C) typedef int GmbH
#  SPDX-License-Identifier: MIT
#
###############################################################################
"""Shared helpers for the python-package aspect's check + reconcile scripts.

The two scripts must agree on what a *source file* is, what counts as *generated*,
what counts as *having a header*, and what the house header looks like - `check.py`
reports exactly what `reconcile.py` fixes. Keeping that here (one definition) is why
they cannot drift. Stdlib-only.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import tomllib

if TYPE_CHECKING:
    from pathlib import Path

HEADER_SCAN = 600  # bytes of a file scanned for a header / generator marker
PROPRIETARY = "LicenseRef-Proprietary"

# Generated files are the generator's concern, not the house header rule's. Detected
# by a marker in the file head (FlatBuffers, protobuf, @generated, ...).
_GENERATED_MARKERS = (
    "automatically generated",
    "do not modify",
    "do not edit",
    "@generated",
)


def get(table: object, *keys: str) -> object:
    """Return a nested value from parsed TOML, or ``None`` if any key is missing."""
    cur: object = table
    for key in keys:
        if not isinstance(cur, dict) or key not in cur:
            return None
        cur = cur[key]
    return cur


def repo_license(repo: Path) -> str | None:
    """Return the repo's ``[project].license`` string, or ``None``."""
    pyproject = repo / "pyproject.toml"
    if not pyproject.is_file():
        return None
    try:
        pp = tomllib.loads(pyproject.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError):
        return None
    lic = get(pp, "project", "license")
    return lic if isinstance(lic, str) and lic else None


def source_files(repo: Path) -> list[Path]:
    """Return all ``src/**/*.py`` files in ``repo`` (sorted); empty if no ``src``."""
    src = repo / "src"
    return sorted(src.rglob("*.py")) if src.is_dir() else []


def _head(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")[:HEADER_SCAN]


def is_generated(path: Path) -> bool:
    """Whether ``path`` carries a generator marker in its head (per-file signal)."""
    head = _head(path).lower()
    return any(marker in head for marker in _GENERATED_MARKERS)


def _generated_dirs(files: list[Path]) -> set[Path]:
    """Directories whose whole subtree is generated code.

    A directory is generated iff its subtree contains at least one marker-bearing file
    AND no *hand-written* file (a ``.py`` that is neither marker-bearing nor an
    ``__init__.py``). This captures a generator's output *tree* - e.g. flatc emits
    marked ``.py`` plus empty/markerless package ``__init__.py`` - without mistaking a
    hand-written package that merely *contains* a generated sub-package for generated.
    """
    has_marker: dict[Path, bool] = {}
    has_handwritten: dict[Path, bool] = {}
    for f in files:
        generated = is_generated(f)
        handwritten = not generated and f.name != "__init__.py"
        for parent in f.parents:
            has_marker[parent] = has_marker.get(parent, False) or generated
            has_handwritten[parent] = has_handwritten.get(parent, False) or handwritten
    return {d for d, marked in has_marker.items() if marked and not has_handwritten[d]}


def non_generated_sources(repo: Path) -> list[Path]:
    """Return ``src/**/*.py`` subject to the header rule - generated code excluded.

    A file is exempt if it carries a generator marker itself, or it lives inside a
    generated directory tree (see :func:`_generated_dirs`). The latter catches the
    empty/markerless ``__init__.py`` a generator emits alongside its marked output: a
    header on those would be stripped by a clean regenerate (= drift). Genuine empty
    ``__init__.py`` (a test or hand-written package marker, whose tree has no generated
    files) are NOT exempt - they still get a header.
    """
    files = source_files(repo)
    gen_dirs = _generated_dirs(files)
    return [
        f
        for f in files
        if not is_generated(f) and not any(d in gen_dirs for d in f.parents)
    ]


def has_header(path: Path) -> bool:
    """Whether ``path`` carries a copyright header."""
    return "Copyright" in _head(path)


def line_count(path: Path) -> int:
    """Return the number of lines in ``path`` (0 for an empty file)."""
    return len(path.read_text(encoding="utf-8", errors="replace").splitlines())


def house_header(spdx: str) -> str:
    """Return the house SPDX / copyright header block for a license id (no year)."""
    copyright_line = (
        "Copyright (C) typedef int GmbH (Germany). All rights reserved."
        if spdx == PROPRIETARY
        else "Copyright (C) typedef int GmbH"
    )
    rule = "#" * 79
    body = f"#\n#  {copyright_line}\n#  SPDX-License-Identifier: {spdx}\n#\n"
    return f"{rule}\n{body}{rule}\n"

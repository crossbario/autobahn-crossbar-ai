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

import fnmatch
import hashlib
import json
import re
import tomllib
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

HEADER_SCAN = 600  # bytes of a file scanned for a header / generator marker
PROPRIETARY = "LicenseRef-Proprietary"
ASPECT = "python-package"

# The house license standard: OSS packages are MIT, closed ones LicenseRef-Proprietary.
# Any other value (EUPL-1.2 included) is a legitimate per-repo choice - but a deviation,
# which must be a signed decision in the target (A18), never silently accepted.
HOUSE_LICENSES = ("MIT", PROPRIETARY)
LICENSE_DEVIATION = "license_deviation"
LICENSE_OPTIONS = ("keep", "relicense:MIT")

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


def _is_empty_init(path: Path) -> bool:
    """Whether ``path`` is an ``__init__.py`` with no code (comments/blank lines only).

    An existing header is comment lines, so a headered-but-otherwise-empty package
    init still counts as empty - the rule stays idempotent once a genuine init is
    headered. A content-bearing ``__init__.py`` (any non-comment, non-blank line) is
    NOT empty: it is hand-written and must be headered, even inside a generated tree.
    """
    if path.name != "__init__.py":
        return False
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        stripped = line.strip()
        if stripped and not stripped.startswith("#"):
            return False
    return True


def _generated_dirs(files: list[Path]) -> set[Path]:
    """Directories whose whole subtree is generated code.

    A directory is generated iff its subtree contains at least one marker-bearing file
    AND no *hand-written* file - a ``.py`` that is neither marker-bearing nor an *empty*
    ``__init__.py``. This captures a generator's output *tree* (e.g. flatc emits marked
    ``.py`` plus empty package ``__init__.py``) without mistaking a hand-written package
    that merely *contains* a generated sub-package, or a content-bearing ``__init__.py``
    that happens to sit in such a tree, for generated.
    """
    has_marker: dict[Path, bool] = {}
    has_handwritten: dict[Path, bool] = {}
    for f in files:
        generated = is_generated(f)
        handwritten = not generated and not _is_empty_init(f)
        for parent in f.parents:
            has_marker[parent] = has_marker.get(parent, False) or generated
            has_handwritten[parent] = has_handwritten.get(parent, False) or handwritten
    return {d for d, marked in has_marker.items() if marked and not has_handwritten[d]}


def non_generated_sources(repo: Path) -> list[Path]:
    """Return ``src/**/*.py`` subject to the header rule - generated code excluded.

    A file is exempt if it carries a generator marker itself, or it is an *empty*
    ``__init__.py`` inside a generated directory tree (see :func:`_generated_dirs`) -
    the package init a generator emits, which a clean regenerate would strip a header
    from (drift). A *content-bearing* ``__init__.py`` is never tree-exempt (it is
    hand-written and gets a header), and a genuine empty ``__init__.py`` outside any
    generated tree (a test or package marker) is not exempt either - both still get a
    header.
    """
    files = source_files(repo)
    gen_dirs = _generated_dirs(files)
    return [
        f
        for f in files
        if not is_generated(f)
        and not (_is_empty_init(f) and any(d in gen_dirs for d in f.parents))
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


# --- canonical digests -----------------------------------------------------------


def canonical_sha256(value: object) -> str:
    """sha256 of the canonical JSON of ``value`` (sorted keys, no whitespace)."""
    text = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def license_observation(repo: Path) -> dict[str, str | None]:
    """What a license decision is answered against: the declared value + LICENSE.

    The keys are the precondition's ``paths``; ``LICENSE`` is the sha256 of the file's
    bytes (``None`` if absent), so any edit to it invalidates the decision.
    """
    lic = repo / "LICENSE"
    return {
        "pyproject.toml#project.license": repo_license(repo),
        "LICENSE": hashlib.sha256(lic.read_bytes()).hexdigest()
        if lic.is_file()
        else None,
    }


# --- decision files (A18; fleet-and-aspect-governance.md §5) ----------------------


class DecisionFileError(ValueError):
    """A decision file that cannot be trusted as written - never silently skipped."""


def _decision_key(name: str, dtype: str) -> tuple[str, int] | None:
    m = re.fullmatch(rf"(\d{{8}})-{re.escape(dtype)}(?:-(\d+))?\.toml", name)
    if m is None:
        return None
    return m.group(1), int(m.group(2) or 1)


def decision_files(repo: Path, dtype: str) -> list[Path]:
    """``.decisions/python-package/<YYYYMMDD>-<dtype>[-N].toml``, oldest first."""
    folder = repo / ".decisions" / ASPECT
    if not folder.is_dir():
        return []
    keyed = []
    for path in folder.iterdir():
        key = _decision_key(path.name, dtype)
        if key is not None:
            keyed.append((key, path))
    return [path for _key, path in sorted(keyed)]


def current_decision(repo: Path, dtype: str) -> tuple[Path, dict] | None:
    """The current decision of type ``dtype``: the NEWEST file, validated.

    Newest wins strictly - an older file is history, never a fallback. Raises
    :class:`DecisionFileError` on anything that cannot be trusted as written: a file
    that is not TOML, names another aspect or type, an answer outside its options, a
    licensing decision not decided by a human, no precondition, or a broken
    ``supersedes`` chain (every file but the first names its predecessor).
    """
    files = decision_files(repo, dtype)
    if not files:
        return None
    for i, path in enumerate(files):
        try:
            data = tomllib.loads(path.read_text(encoding="utf-8"))
        except (OSError, tomllib.TOMLDecodeError) as exc:
            msg = f"{path.name}: not a readable TOML decision file: {exc}"
            raise DecisionFileError(msg) from exc
        expected = files[i - 1].name if i else None
        _validate(path, data, dtype, expected)
    return files[-1], tomllib.loads(files[-1].read_text(encoding="utf-8"))


def _license_problems(data: dict) -> list[str]:
    problems = []
    if data.get("answer") not in LICENSE_OPTIONS:
        problems.append(f"answer {data.get('answer')!r} unknown to this aspect")
    if data.get("decided_by") != "human":
        problems.append("a licensing decision must be decided_by = 'human'")
    return problems


def _validate(path: Path, data: dict, dtype: str, supersedes: str | None) -> None:
    problems = []
    if data.get("schema") != 1:
        problems.append(f"schema {data.get('schema')!r} (expected 1)")
    if data.get("aspect") != ASPECT:
        problems.append(f"aspect {data.get('aspect')!r} (expected {ASPECT!r})")
    if data.get("type") != dtype:
        problems.append(f"type {data.get('type')!r} (expected {dtype!r})")
    options = data.get("options")
    if not isinstance(options, list) or data.get("answer") not in options:
        problems.append(f"answer {data.get('answer')!r} is not one of {options!r}")
    if dtype == LICENSE_DEVIATION:
        problems += _license_problems(data)
    pre = get(data, "precondition", "sha256")
    if not (isinstance(pre, str) and re.fullmatch(r"[0-9a-f]{64}", pre)):
        problems.append("no [precondition] sha256")
    if data.get("supersedes") != supersedes:
        problems.append(
            f"supersedes {data.get('supersedes')!r} (expected {supersedes!r})"
        )
    if problems:
        msg = f"{path.name}: " + "; ".join(problems)
        raise DecisionFileError(msg)


# --- submodules must not be linted as the package's own code --------------------


def submodule_paths(repo: Path) -> list[str]:
    """The ``path = ...`` entries of the repo's ``.gitmodules`` (sorted)."""
    gm = repo / ".gitmodules"
    if not gm.is_file():
        return []
    text = gm.read_text(encoding="utf-8")
    return sorted(
        {m.group(1).strip() for m in re.finditer(r"(?m)^\s*path\s*=\s*(.+)$", text)}
    )


def ruff_excludes(pp: dict) -> list[str] | None:
    """``[tool.ruff]`` exclude + extend-exclude; ``None`` if ruff is not configured."""
    ruff = get(pp, "tool", "ruff")
    if not isinstance(ruff, dict):
        return None
    out: list[str] = []
    for key in ("exclude", "extend-exclude"):
        value = ruff.get(key)
        if isinstance(value, list):
            out += [str(v) for v in value]
    return out


def unexcluded_submodules(repo: Path, pp: dict) -> list[str] | None:
    """Submodule paths ruff would lint as package code (``None``: no ruff config)."""
    excludes = ruff_excludes(pp)
    if excludes is None:
        return None
    patterns = [
        e.strip().removeprefix("./").removeprefix("/").rstrip("/") for e in excludes
    ]
    return [p for p in submodule_paths(repo) if not _excluded(p, patterns)]


def _excluded(path: str, patterns: list[str]) -> bool:
    """Whether a ruff exclude pattern covers ``path``: the path or a parent, as a glob.

    Top-level ``[tool.ruff]`` excludes only - they apply to ``ruff check`` *and*
    ``ruff format``; a ``[tool.ruff.lint]`` exclude still lets the formatter in.
    """
    parts = path.split("/")
    prefixes = ["/".join(parts[: i + 1]) for i in range(len(parts))]
    return any(fnmatch.fnmatchcase(pre, pat) for pat in patterns for pre in prefixes)


# --- open decisions (A18): a required decision nobody has taken yet --------------


def open_decision_files(repo: Path) -> list[tuple[str, str]]:
    """``[(repo-relative path, question)]`` of every ``.decisions/*/OPEN-*.toml``.

    The fleet driver records a question it cannot answer as such a file in the target
    (typedefint/aaiare-fleet-manager#42); the maintainer's signed decision renames it
    into the decision file. While one exists, the reconciliation is stopped by design.
    """
    root = repo / ".decisions"
    if not root.is_dir():
        return []
    found = []
    for path in sorted(root.glob("*/OPEN-*.toml")):
        try:
            question = tomllib.loads(path.read_text(encoding="utf-8")).get("question")
        except (OSError, tomllib.TOMLDecodeError):
            question = None
        found.append(
            (path.relative_to(repo).as_posix(), str(question or "(unreadable)"))
        )
    return found

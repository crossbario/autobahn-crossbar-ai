###############################################################################
#
#  Copyright (C) typedef int GmbH
#  SPDX-License-Identifier: MIT
#
###############################################################################
"""Shared helpers for the zlmdb-py-lmdb-fork aspect's check + reconcile scripts.

Both scripts compare the same *observation* of the target (what the fork vendors)
with the same *baseline* (what upstream py-lmdb ships), so they cannot disagree on
what drifted. Stdlib-only; reads the target tree and its git objects, never the
network.

Two kinds of difference are kept apart:

- **drift** - the fork is not at the baseline's py-lmdb version or LMDB tags. Not
  decidable: the fork has to be brought in sync (a port), then it converges.
- **deviation** - a vendored patch that differs from upstream's (missing, changed or
  added), or an upstream test case the fork does not carry. Legitimate when intended
  (zlmdb is CFFI-only, so it does not vendor the C extension's symbol-rename header),
  so it is a signed decision in the target (A18), never silently accepted.
"""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
import tomllib
from dataclasses import dataclass
from pathlib import Path

ASPECT = "zlmdb-py-lmdb-fork"
ASPECT_DIR = Path(__file__).resolve().parents[1]
BASELINE = ASPECT_DIR / "references" / "upstream-baseline.toml"

DEVIATION = "baseline_deviation"
DEVIATION_OPTIONS = ("accept", "port")

_FORKED_FROM = re.compile(
    r"""(?m)^__forked_from__\s*=\s*['"]py-lmdb\s+([0-9][0-9A-Za-z.]*)['"]"""
)
_TEST_CASE = re.compile(r"(?m)^\s*def (test_\w+)\s*\(")


class DecisionFileError(ValueError):
    """A decision file that cannot be trusted as written - never silently skipped."""


@dataclass(frozen=True)
class Engine:
    """One bundled LMDB release line: where the fork keeps it, what upstream pins."""

    key: str  # baseline key: "lib" (LMDB 0.9) or "lib1" (LMDB 1.0), as in py-lmdb
    submodule: str  # target path of the LMDB source submodule
    patches: str  # target directory of the vendored patch series
    tag: str  # pinned LMDB tag
    commit: str  # the commit that tag names
    files: dict[str, str]  # upstream patch-series file name -> sha256


@dataclass(frozen=True)
class Spec:
    """The aspect's target layout (aspect.toml) joined with the upstream baseline."""

    vendor_init: str
    tests_dir: str
    py_lmdb: str
    engines: tuple[Engine, ...]
    tests: dict[str, tuple[str, ...]]  # upstream test module -> its test case names


def load_spec(baseline: Path = BASELINE) -> Spec:
    """Read the target layout from ``aspect.toml`` and the pinned upstream baseline."""
    aspect = tomllib.loads((ASPECT_DIR / "aspect.toml").read_text(encoding="utf-8"))
    base = tomllib.loads(baseline.read_text(encoding="utf-8"))
    target = aspect["target"]
    engines = tuple(
        Engine(
            key=key,
            submodule=layout["submodule"],
            patches=layout["patches"],
            tag=base["lmdb"][key]["tag"],
            commit=base["lmdb"][key]["commit"],
            files=dict(base["patches"][key]),
        )
        for key, layout in sorted(target["engine"].items())
    )
    return Spec(
        vendor_init=target["vendor_init"],
        tests_dir=target["tests_dir"],
        py_lmdb=base["py-lmdb"]["version"],
        engines=engines,
        tests={name: tuple(t["cases"]) for name, t in sorted(base["tests"].items())},
    )


def applicable(repo: Path, spec: Spec) -> bool:
    """Whether ``repo`` vendors the fork at all (has the vendored package's init)."""
    return (repo / spec.vendor_init).is_file()


def forked_from(repo: Path, spec: Spec) -> str | None:
    """The py-lmdb version the vendored package says it was forked from."""
    m = _FORKED_FROM.search((repo / spec.vendor_init).read_text(encoding="utf-8"))
    return m.group(1) if m else None


def gitlink(repo: Path, path: str) -> str | None:
    """The commit a submodule is pinned to in ``HEAD`` (``None``: no such gitlink).

    Read from the target's own git objects, so it needs no network and no initialized
    submodule, and gives the same answer on every host for the same commit.
    """
    try:
        out = subprocess.run(  # noqa: S603 - fixed program, a path + a repo path
            ["git", "-C", str(repo), "ls-tree", "-z", "HEAD", "--", path],  # noqa: S607
            capture_output=True,
            text=True,
            check=True,
        ).stdout
    except (OSError, subprocess.CalledProcessError):
        return None
    for entry in out.split("\0"):
        meta, _, name = entry.partition("\t")
        fields = meta.split()
        if name == path and len(fields) == 3 and fields[0] == "160000":  # noqa: PLR2004
            return fields[2]
    return None


def file_hashes(directory: Path) -> dict[str, str]:
    """``{file name: sha256}`` of the regular files directly in ``directory``."""
    if not directory.is_dir():
        return {}
    return {
        p.name: hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(directory.iterdir())
        if p.is_file()
    }


def test_cases(path: Path) -> set[str]:
    """The ``test_*`` function / method names defined in a test module."""
    if not path.is_file():
        return set()
    return set(_TEST_CASE.findall(path.read_text(encoding="utf-8", errors="replace")))


def drift(repo: Path, spec: Spec) -> list[dict[str, str | None]]:
    """What is not at the baseline: the py-lmdb version and each LMDB pin."""
    found: list[dict[str, str | None]] = []
    version = forked_from(repo, spec)
    if version != spec.py_lmdb:
        found.append(
            {
                "what": "py-lmdb",
                "path": spec.vendor_init,
                "expected": spec.py_lmdb,
                "observed": version,
            }
        )
    for engine in spec.engines:
        pinned = gitlink(repo, engine.submodule)
        if pinned != engine.commit:
            found.append(
                {
                    "what": f"LMDB ({engine.key})",
                    "path": engine.submodule,
                    "expected": f"{engine.tag} ({engine.commit})",
                    "observed": pinned,
                }
            )
    return found


def deviations(repo: Path, spec: Spec) -> list[dict[str, str]]:
    """Every patch and test-case difference from the baseline, in a stable order."""
    found: list[dict[str, str]] = []
    for engine in spec.engines:
        have = file_hashes(repo / engine.patches)
        for name in sorted(set(engine.files) | set(have)):
            if name not in have:
                kind = "patch_missing"
            elif name not in engine.files:
                kind = "patch_added"
            elif have[name] != engine.files[name]:
                kind = "patch_changed"
            else:
                continue
            found.append({"kind": kind, "path": f"{engine.patches}/{name}"})
    for module, cases in spec.tests.items():
        have_cases = test_cases(repo / spec.tests_dir / module)
        found += [
            {"kind": "test_missing", "path": f"{spec.tests_dir}/{module}::{case}"}
            for case in sorted(set(cases) - have_cases)
        ]
    return found


# --- canonical digests -----------------------------------------------------------


def canonical_sha256(value: object) -> str:
    """sha256 of the canonical JSON of ``value`` (sorted keys, no whitespace)."""
    text = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# --- decision files (A18; fleet-and-aspect-governance.md §5) ----------------------


def _decision_key(name: str) -> tuple[str, int] | None:
    m = re.fullmatch(rf"(\d{{8}})-{DEVIATION}(?:-(\d+))?\.toml", name)
    if m is None:
        return None
    return m.group(1), int(m.group(2) or 1)


def decision_files(repo: Path) -> list[Path]:
    """``.decisions/zlmdb-py-lmdb-fork/<YYYYMMDD>-baseline_deviation[-N].toml``."""
    folder = repo / ".decisions" / ASPECT
    if not folder.is_dir():
        return []
    keyed = []
    for path in folder.iterdir():
        key = _decision_key(path.name)
        if key is not None:
            keyed.append((key, path))
    return [path for _key, path in sorted(keyed)]


def current_decision(repo: Path) -> tuple[Path, dict] | None:
    """The current deviation decision: the NEWEST file, the whole chain validated.

    Newest wins strictly - an older file is history, never a fallback. Raises
    :class:`DecisionFileError` on anything that cannot be trusted as written.
    """
    files = decision_files(repo)
    if not files:
        return None
    data: dict = {}
    for i, path in enumerate(files):
        try:
            data = tomllib.loads(path.read_text(encoding="utf-8"))
        except (OSError, tomllib.TOMLDecodeError) as exc:
            msg = f"{path.name}: not a readable TOML decision file: {exc}"
            raise DecisionFileError(msg) from exc
        _validate(path, data, files[i - 1].name if i else None)
    return files[-1], data


def _validate(path: Path, data: dict, supersedes: str | None) -> None:
    problems = []
    if data.get("schema") != 1:
        problems.append(f"schema {data.get('schema')!r} (expected 1)")
    if data.get("aspect") != ASPECT:
        problems.append(f"aspect {data.get('aspect')!r} (expected {ASPECT!r})")
    if data.get("type") != DEVIATION:
        problems.append(f"type {data.get('type')!r} (expected {DEVIATION!r})")
    if data.get("answer") not in DEVIATION_OPTIONS:
        problems.append(f"answer {data.get('answer')!r} unknown to this aspect")
    options = data.get("options")
    if not isinstance(options, list) or data.get("answer") not in options:
        problems.append(f"answer {data.get('answer')!r} is not one of {options!r}")
    if data.get("decided_by") != "human":
        problems.append("a deviation from upstream must be decided_by = 'human'")
    pre = data.get("precondition")
    sha = pre.get("sha256") if isinstance(pre, dict) else None
    if not (isinstance(sha, str) and re.fullmatch(r"[0-9a-f]{64}", sha)):
        problems.append("no [precondition] sha256")
    if data.get("supersedes") != supersedes:
        problems.append(
            f"supersedes {data.get('supersedes')!r} (expected {supersedes!r})"
        )
    if problems:
        msg = f"{path.name}: " + "; ".join(problems)
        raise DecisionFileError(msg)


def open_decision_files(repo: Path) -> list[tuple[str, str]]:
    """``[(repo-relative path, question)]`` of this aspect's ``OPEN-*.toml`` files.

    The fleet driver records a question it cannot answer as such a file; the
    maintainer's signed decision replaces it. While one exists, the reconcile stops.
    """
    folder = repo / ".decisions" / ASPECT
    if not folder.is_dir():
        return []
    found = []
    for path in sorted(folder.glob("OPEN-*.toml")):
        try:
            question = tomllib.loads(path.read_text(encoding="utf-8")).get("question")
        except (OSError, tomllib.TOMLDecodeError):
            question = None
        found.append(
            (path.relative_to(repo).as_posix(), str(question or "(unreadable)"))
        )
    return found

# Copyright (c) typedef int GmbH, Germany, 2026. All rights reserved.
# SPDX-License-Identifier: MIT
"""Check a Python package against the AAIARE house standard (``python-package`` aspect).

Standalone and stdlib-only: it reads ``<repo>/pyproject.toml`` and reports a finding
per rule. See ``../SKILL.md`` for the semantics and
``../references/house-standard.md`` for the rules in detail. It imports nothing from
the fleet engine, so it runs anywhere Python 3.11+ is available.

Usage::

    python check.py <repo> [<repo> ...]
    python check.py --json <repo> [<repo> ...]

Exit code: 0 if no rule FAILs (WARN allowed), 1 if any repo FAILs, 2 on usage error.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

import tomllib

OK = "OK"
WARN = "WARN"
FAIL = "FAIL"

MIN_PYTHON = (3, 11)
_CALVER = re.compile(r"^(\d+)\.(\d+)\.(\d+)")
_MINPY = re.compile(r">=\s*(\d+)\.(\d+)")


@dataclass(frozen=True)
class Finding:
    """One rule's verdict for one repository."""

    rule: str
    status: str
    message: str


def _get(table: object, *keys: str) -> object:
    """Return a nested value from parsed TOML, or ``None`` if any key is missing."""
    cur: object = table
    for key in keys:
        if not isinstance(cur, dict) or key not in cur:
            return None
        cur = cur[key]
    return cur


def _check_build_backend(pp: dict) -> Finding:
    backend = _get(pp, "build-system", "build-backend")
    requires = _get(pp, "build-system", "requires") or []
    uses_hatchling = any("hatchling" in str(r) for r in requires)
    if backend == "hatchling.build" and uses_hatchling:
        return Finding("build-backend", OK, "hatchling.build")
    return Finding(
        "build-backend",
        FAIL,
        f"must be hatchling.build (got build-backend={backend!r})",
    )


def _check_version(pp: dict) -> Finding:
    version = _get(pp, "project", "version")
    if not isinstance(version, str):
        return Finding("version", FAIL, "no [project].version")
    m = _CALVER.match(version)
    if not m:
        return Finding("version", FAIL, f"not CalVer YY.M.MICRO: {version!r}")
    micro = int(m.group(3))
    if micro < 1:
        return Finding("version", FAIL, f"MICRO must be >= 1 (never .0): {version!r}")
    return Finding("version", OK, f"CalVer {version}")


def _check_requires_python(pp: dict) -> Finding:
    spec = _get(pp, "project", "requires-python")
    if not isinstance(spec, str):
        return Finding("requires-python", WARN, "no [project].requires-python")
    m = _MINPY.search(spec)
    if not m:
        return Finding("requires-python", WARN, f"no lower bound found: {spec!r}")
    floor = (int(m.group(1)), int(m.group(2)))
    if floor < MIN_PYTHON:
        return Finding(
            "requires-python",
            FAIL,
            f"floor {floor[0]}.{floor[1]} is below {MIN_PYTHON[0]}.{MIN_PYTHON[1]}",
        )
    return Finding("requires-python", OK, spec)


def _check_license(pp: dict) -> Finding:
    lic = _get(pp, "project", "license")
    if isinstance(lic, str) and lic:
        return Finding("license", OK, lic)
    return Finding("license", WARN, "no PEP 639 [project].license string")


def _check_headers(repo: Path) -> Finding:
    src = repo / "src"
    files = sorted(src.rglob("*.py"))[:20] if src.is_dir() else []
    if not files:
        return Finding("spdx-headers", WARN, "no src/**.py sampled")
    missing = [
        f.relative_to(repo).as_posix()
        for f in files
        if "Copyright" not in f.read_text(encoding="utf-8", errors="replace")[:600]
    ]
    if missing:
        return Finding(
            "spdx-headers", WARN, f"no copyright header in {len(missing)} file(s)"
        )
    return Finding("spdx-headers", OK, f"present in {len(files)} sampled file(s)")


def inspect_repo(repo: Path) -> list[Finding]:
    """Return the house-standard findings for ``repo``."""
    pyproject = repo / "pyproject.toml"
    if not pyproject.is_file():
        return [Finding("pyproject", FAIL, "no pyproject.toml")]
    try:
        pp = tomllib.loads(pyproject.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as exc:
        return [Finding("pyproject", FAIL, f"unreadable pyproject.toml: {exc}")]
    return [
        _check_build_backend(pp),
        _check_version(pp),
        _check_requires_python(pp),
        _check_license(pp),
        _check_headers(repo),
    ]


def _worst(findings: list[Finding]) -> str:
    if any(f.status == FAIL for f in findings):
        return FAIL
    if any(f.status == WARN for f in findings):
        return WARN
    return OK


def main(argv: list[str] | None = None) -> int:
    """Run the checker over the given repositories and print a report."""
    parser = argparse.ArgumentParser(
        description="Check Python packages against the house standard."
    )
    parser.add_argument(
        "repos", nargs="+", type=Path, help="repository directories to check"
    )
    parser.add_argument("--json", action="store_true", help="emit findings as JSON")
    args = parser.parse_args(argv)

    results = {repo.name: inspect_repo(repo) for repo in args.repos}

    if args.json:
        payload = {
            name: {"verdict": _worst(fs), "findings": [asdict(f) for f in fs]}
            for name, fs in results.items()
        }
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        for name, fs in results.items():
            print(f"\n{name}: {_worst(fs)}")
            for f in fs:
                print(f"  [{f.status:4}] {f.rule}: {f.message}")

    return 1 if any(_worst(fs) == FAIL for fs in results.values()) else 0


if __name__ == "__main__":
    sys.exit(main())

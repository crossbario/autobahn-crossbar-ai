###############################################################################
#
#  Copyright (C) typedef int GmbH
#  SPDX-License-Identifier: MIT
#
###############################################################################
"""Check a Python package against the AAIARE house standard (``python-package`` aspect).

Standalone and stdlib-only (Python 3.11+); imports nothing from the fleet engine. It
reads ``<repo>/pyproject.toml`` + source tree and reports a finding per rule. See
``../SKILL.md`` for semantics and ``../references/house-standard.md`` for the rules.
Shared file/header logic lives in ``_pp.py`` so this agrees with ``reconcile.py``.

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
import tomllib
from dataclasses import asdict, dataclass
from pathlib import Path

from _pp import (
    HOUSE_LICENSES,
    LICENSE_DEVIATION,
    DecisionFileError,
    canonical_sha256,
    current_decision,
    get,
    has_header,
    license_observation,
    non_generated_sources,
    open_decision_files,
    unexcluded_submodules,
)

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


def _check_build_backend(pp: dict) -> Finding:
    backend = get(pp, "build-system", "build-backend")
    requires = get(pp, "build-system", "requires")
    if not isinstance(requires, list):
        requires = []
    if backend == "hatchling.build" and any("hatchling" in str(r) for r in requires):
        return Finding("build-backend", OK, "hatchling.build")
    return Finding("build-backend", FAIL, f"must be hatchling.build (got {backend!r})")


def _check_version(pp: dict) -> Finding:
    version = get(pp, "project", "version")
    if not isinstance(version, str):
        return Finding("version", FAIL, "no [project].version")
    m = _CALVER.match(version)
    if not m:
        return Finding("version", FAIL, f"not CalVer YY.M.MICRO: {version!r}")
    if int(m.group(3)) < 1:
        return Finding("version", FAIL, f"MICRO must be >= 1 (never .0): {version!r}")
    return Finding("version", OK, f"CalVer {version}")


def _check_requires_python(pp: dict) -> Finding:
    spec = get(pp, "project", "requires-python")
    if not isinstance(spec, str):
        return Finding("requires-python", WARN, "no [project].requires-python")
    m = _MINPY.search(spec)
    if not m:
        return Finding("requires-python", WARN, f"no lower bound found: {spec!r}")
    if (int(m.group(1)), int(m.group(2))) < MIN_PYTHON:
        return Finding(
            "requires-python",
            FAIL,
            f"floor below {MIN_PYTHON[0]}.{MIN_PYTHON[1]}: {spec}",
        )
    return Finding("requires-python", OK, spec)


def _check_license(pp: dict, repo: Path) -> Finding:
    lic = get(pp, "project", "license")
    if not (isinstance(lic, str) and lic):
        return Finding("license", WARN, "no PEP 639 [project].license string")
    if lic in HOUSE_LICENSES:
        return Finding("license", OK, lic)
    try:
        found = current_decision(repo, LICENSE_DEVIATION)
    except DecisionFileError as exc:
        return Finding("license", FAIL, f"{lic}: untrustworthy decision file: {exc}")
    pre = canonical_sha256(license_observation(repo))
    if found is not None and get(found[1], "precondition", "sha256") == pre:
        return Finding(
            "license",
            WARN,
            f"{lic}: deviation from the house standard, decided "
            f"{found[1]['answer']!r} in .decisions/python-package/{found[0].name}",
        )
    stale = " (the recorded decision is stale: re-decide)" if found else ""
    return Finding(
        "license",
        WARN,
        f"{lic}: deviation from the house standard ({', '.join(HOUSE_LICENSES)}) - "
        f"a signed decision is required{stale}",
    )


def _check_open_decisions(repo: Path) -> Finding:
    opened = open_decision_files(repo)
    if not opened:
        return Finding("open-decisions", OK, "no open decision")
    listing = "; ".join(f"{path} ({question})" for path, question in opened)
    return Finding(
        "open-decisions",
        FAIL,
        f"{len(opened)} required decision(s) not taken - decide before landing: "
        f"{listing}",
    )


def _check_lint_excludes(pp: dict, repo: Path) -> Finding:
    missing = unexcluded_submodules(repo, pp)
    if missing is None:
        return Finding("lint-excludes", OK, "no [tool.ruff] configuration")
    if missing:
        return Finding(
            "lint-excludes",
            FAIL,
            "submodules ruff would lint as this package's code - add to "
            f"[tool.ruff] extend-exclude: {', '.join(missing)}",
        )
    return Finding("lint-excludes", OK, "every submodule is excluded from ruff")


def _check_headers(repo: Path) -> Finding:
    files = non_generated_sources(repo)
    if not files:
        return Finding("spdx-headers", WARN, "no non-generated src/**.py")
    missing = [f for f in files if not has_header(f)]
    if missing:
        return Finding(
            "spdx-headers",
            WARN,
            f"no header in {len(missing)} of {len(files)} non-generated file(s)",
        )
    return Finding(
        "spdx-headers", OK, f"present in all {len(files)} non-generated file(s)"
    )


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
        _check_license(pp, repo),
        _check_headers(repo),
        _check_lint_excludes(pp, repo),
        _check_open_decisions(repo),
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

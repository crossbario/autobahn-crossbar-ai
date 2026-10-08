###############################################################################
#
#  Copyright (C) typedef int GmbH
#  SPDX-License-Identifier: MIT
#
###############################################################################
"""Compute the rollout ChangeSet for the ``python-package`` aspect (headers only).

Standalone and stdlib-only (Python 3.11+); imports nothing from the reconciler engine.
It reads a repo's ``pyproject.toml`` + source tree and **emits a ChangeSet as JSON**
that a consumer (the engine, or a thin applier) applies; this script only *computes*,
it changes nothing.

Scope today: add the house SPDX / copyright header to non-generated source files that
have no header. Shared file/header logic lives in ``_pp.py`` so this agrees with
``check.py``: *generated* files are exempt (the generator owns their header), and a
file with any ``Copyright`` line already counts as headed (enforcing the *exact*
house banner is a stricter rule for later). "Generated" is a *tree*, not just a
per-file marker: the empty/markerless ``__init__.py`` a generator emits alongside its
marked output are exempt too (``_pp.non_generated_sources``). Output is canonical +
deterministic (ops sorted by path, no timestamps/env), so the same inputs yield the
same JSON and ``digest``.

Usage::

    python reconcile.py <repo> [<repo> ...]
    python reconcile.py --json <repo> [<repo> ...]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import tomllib
from pathlib import Path

from _pp import (
    HOUSE_LICENSES,
    LICENSE_DEVIATION,
    LICENSE_OPTIONS,
    PROPRIETARY,
    DecisionFileError,
    canonical_sha256,
    current_decision,
    get,
    has_header,
    house_header,
    license_observation,
    line_count,
    non_generated_sources,
    repo_license,
    unexcluded_submodules,
)


def _digest(changes: list[dict]) -> str:
    canonical = json.dumps(
        changes, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _result(
    changes: list[dict[str, object]],
    decisions: list[dict],
    *,
    applicable: bool = True,
) -> dict:
    changes = sorted(changes, key=lambda c: (str(c["path"]), str(c["action"])))
    return {
        "applicable": applicable,
        "changeset": changes,
        "decisions_required": decisions,
        "digest": _digest(changes),
    }


def _license_deviation(repo: Path, spdx: str) -> tuple[str | None, list[dict]]:
    """The license the headers use, or ``None`` with what stops the reconcile.

    A deviation from the house licenses is decided by a human, in a signed decision
    file in the target: no current decision, or one answered against a different
    observed state (precondition), re-raises the request - an old answer is never
    applied to a changed repository. ``keep`` proceeds with the declared license.
    ``relicense:MIT`` is a legal act the aspect never performs: the reconcile stays
    stopped until the maintainer's own relicensing change lands (then the license is
    MIT and no deviation remains).
    """
    observed = license_observation(repo)
    pre = canonical_sha256(observed)
    found = current_decision(repo, LICENSE_DEVIATION)
    if found is not None:
        path, decision = found
        if get(decision, "precondition", "sha256") == pre:
            if decision["answer"] == "keep":
                return spdx, []
            return None, [
                {
                    "type": "license_relicense_pending",
                    "path": "pyproject.toml",
                    "decision": f".decisions/python-package/{path.name}",
                    "question": (
                        f"Relicensing {spdx} -> MIT was decided; it is a legal act "
                        "made by the maintainer in its own change ([project].license, "
                        "LICENSE, the headers). The aspect does not perform it."
                    ),
                }
            ]
    request = {
        "type": LICENSE_DEVIATION,
        "path": "pyproject.toml",
        "question": (
            f"House standard: OSS = MIT, closed = {PROPRIETARY}. This package "
            f"declares {spdx}. Keep it?"
        ),
        "options": list(LICENSE_OPTIONS),
        "decided_by": ["human"],
        "precondition": {"paths": sorted(observed), "sha256": pre},
        "observed": observed,
    }
    if found is not None:
        request["stale_decision"] = f".decisions/python-package/{found[0].name}"
    return None, [request]


def reconcile_repo(repo: Path) -> dict:
    """Compute the ChangeSet (and any decisions) for one repository.

    Raises:
        DecisionFileError: If a decision file cannot be trusted as written.
    """
    pyproject = repo / "pyproject.toml"
    if not pyproject.is_file():  # not a Python package: nothing to ask, nothing to do
        return _result([], [], applicable=False)
    spdx = repo_license(repo)
    if spdx is None:
        request = {
            "type": "license_required",
            "path": "pyproject.toml",
            "question": "No [project].license; cannot choose a header. Which license?",
            "options": ["MIT", "EUPL-1.2", PROPRIETARY],
            "observed_sha256": None,
        }
        return _result([], [request])
    if spdx not in HOUSE_LICENSES:
        spdx, stop = _license_deviation(repo, spdx)
        if spdx is None:
            return _result([], stop)

    header = house_header(spdx)
    changes: list[dict[str, object]] = [
        {
            "kind": "file_modify",
            "path": path.relative_to(repo).as_posix(),
            "action": "prepend_header",
            "license": spdx,
            "loc": line_count(path),
            "header": header,
        }
        for path in non_generated_sources(repo)
        if not has_header(path)
    ]
    pp = tomllib.loads(pyproject.read_text(encoding="utf-8"))
    missing = unexcluded_submodules(repo, pp)
    if missing:
        changes.append(
            {
                "kind": "file_modify",
                "path": "pyproject.toml",
                "action": "ruff_extend_exclude",
                "add": missing,
            }
        )
    return _result(changes, [])


def main(argv: list[str] | None = None) -> int:
    """Compute the ChangeSet for each repository and print it."""
    parser = argparse.ArgumentParser(
        description="Compute the python-package rollout ChangeSet."
    )
    parser.add_argument("repos", nargs="+", type=Path, help="repository directories")
    parser.add_argument(
        "--json", action="store_true", help="emit the ChangeSet as JSON"
    )
    args = parser.parse_args(argv)

    try:
        results = {repo.name: reconcile_repo(repo) for repo in args.repos}
    except DecisionFileError as exc:
        print(f"reconcile.py: error: {exc}", file=sys.stderr)
        return 2

    if args.json:
        print(json.dumps(results, indent=2, sort_keys=True))
        return 0

    for name, r in results.items():
        if not r["applicable"]:
            print(f"\n{name}: not applicable (no pyproject.toml)")
            continue
        digest = r["digest"][:12]
        n_c = len(r["changeset"])
        n_d = len(r["decisions_required"])
        print(f"\n{name}: {n_c} change(s), {n_d} decision(s) [{digest}]")
        for c in r["changeset"]:
            if c["action"] == "prepend_header":
                detail = f"({c['license']}): {c['path']} (current {c['loc']} LOC)"
            else:
                detail = f"{c['path']}: {', '.join(c['add'])}"
            print(f"  + {c['action']} {detail}")
        for d in r["decisions_required"]:
            print(f"  ? {d['type']}: {d['question']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

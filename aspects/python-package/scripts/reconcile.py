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
file with any ``Copyright`` line already counts as headed (enforcing the *exact* house
banner is a stricter rule for later). "Generated" is a *tree*, not just a per-file marker:
the empty/markerless ``__init__.py`` a generator emits alongside its marked output are
exempt too (``_pp.non_generated_sources``). Output is canonical + deterministic (ops sorted
by path, no timestamps/env), so the same inputs yield the same JSON and ``digest``.

Usage::

    python reconcile.py <repo> [<repo> ...]
    python reconcile.py --json <repo> [<repo> ...]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

from _pp import (
    PROPRIETARY,
    has_header,
    house_header,
    line_count,
    non_generated_sources,
    repo_license,
)


def _digest(changes: list[dict]) -> str:
    canonical = json.dumps(
        changes, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def reconcile_repo(repo: Path) -> dict:
    """Compute the header ChangeSet (and any decisions) for one repository."""
    spdx = repo_license(repo)
    if spdx is None:
        request = {
            "type": "license_required",
            "path": "pyproject.toml",
            "question": "No [project].license; cannot choose a header. Which license?",
            "options": ["MIT", "EUPL-1.2", PROPRIETARY],
            "observed_sha256": None,
        }
        return {"changeset": [], "decisions_required": [request], "digest": _digest([])}

    header = house_header(spdx)
    changes = [
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
    changes.sort(key=lambda c: c["path"])
    return {"changeset": changes, "decisions_required": [], "digest": _digest(changes)}


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

    results = {repo.name: reconcile_repo(repo) for repo in args.repos}

    if args.json:
        print(json.dumps(results, indent=2, sort_keys=True))
        return 0

    for name, r in results.items():
        digest = r["digest"][:12]
        n_c = len(r["changeset"])
        n_d = len(r["decisions_required"])
        print(f"\n{name}: {n_c} change(s), {n_d} decision(s) [{digest}]")
        for c in r["changeset"]:
            print(
                f"  + {c['action']} ({c['license']}): "
                f"{c['path']} (current {c['loc']} LOC)"
            )
        for d in r["decisions_required"]:
            print(f"  ? {d['type']}: {d['path']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

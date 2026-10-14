###############################################################################
#
#  Copyright (C) typedef int GmbH
#  SPDX-License-Identifier: MIT
#
###############################################################################
"""Compute the rollout ChangeSet for the ``zlmdb-py-lmdb-fork`` aspect.

Standalone and stdlib-only (Python 3.11+); imports nothing from the reconciler engine.
It reads the target tree and the aspect's pinned baseline and **emits a ChangeSet as
JSON**; it changes nothing.

The ChangeSet is always empty: bringing a fork in sync with upstream is a port made
by a person or an agent (see ``../SKILL.md``), not file operations. What this script
does compute is what stops the rollout:

- ``port_required`` - the fork is not at the baseline's py-lmdb version or LMDB tags;
- ``baseline_deviation`` - a decision request for differences from upstream's patch
  series or test cases that no current signed decision covers;
- ``port_pending`` - those differences were decided ``port``, but not ported yet.

Output is canonical and deterministic (sorted, no timestamps or environment), so the
same inputs give byte-identical JSON and ``digest`` on every host.

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

from _fork import (
    ASPECT,
    DEVIATION,
    DEVIATION_OPTIONS,
    DecisionFileError,
    Spec,
    applicable,
    canonical_sha256,
    current_decision,
    deviations,
    drift,
    load_spec,
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


def _port_required(found: list[dict]) -> list[dict]:
    return [
        {
            "type": "port_required",
            "path": d["path"],
            "question": (
                f"{d['what']} is at {d['observed'] or 'nothing'}, the baseline at "
                f"{d['expected']}: bring the fork in sync (SKILL.md, 'Port')."
            ),
        }
        for d in found
    ]


def _deviation_requests(repo: Path, found: list[dict]) -> list[dict]:
    """What the deviations from upstream need: nothing, a decision, or a port."""
    if not found:
        return []
    pre = canonical_sha256(found)
    decided = current_decision(repo)
    if decided is not None:
        path, decision = decided
        if decision["precondition"]["sha256"] == pre:
            if decision["answer"] == "accept":
                return []
            return [
                {
                    "type": "port_pending",
                    "path": f".decisions/{ASPECT}/{path.name}",
                    "question": (
                        f"{len(found)} difference(s) from upstream were decided "
                        "'port': bring them in line with the baseline."
                    ),
                }
            ]
    request = {
        "type": DEVIATION,
        "path": f".decisions/{ASPECT}",
        "question": (
            f"The fork differs from upstream in {len(found)} place(s): vendored "
            "patches or upstream test cases. Accept these as intended, or port them?"
        ),
        "options": list(DEVIATION_OPTIONS),
        "decided_by": ["human"],
        "precondition": {"sha256": pre},
        "observed": found,
    }
    if decided is not None:
        request["stale_decision"] = f".decisions/{ASPECT}/{decided[0].name}"
    return [request]


def reconcile_repo(repo: Path, spec: Spec) -> dict:
    """Compute the (empty) ChangeSet and what stops the rollout, for one repository.

    Raises:
        DecisionFileError: If a decision file cannot be trusted as written.
    """
    if not applicable(repo, spec):  # does not vendor the fork: nothing to ask or do
        return _result([], [], applicable=False)
    stops = _port_required(drift(repo, spec))
    stops += _deviation_requests(repo, deviations(repo, spec))
    return _result([], stops)


def main(argv: list[str] | None = None) -> int:
    """Compute the ChangeSet for each repository and print it."""
    parser = argparse.ArgumentParser(
        description="Compute the zlmdb-py-lmdb-fork rollout ChangeSet."
    )
    parser.add_argument("repos", nargs="+", type=Path, help="repository directories")
    parser.add_argument(
        "--json", action="store_true", help="emit the ChangeSet as JSON"
    )
    args = parser.parse_args(argv)

    spec = load_spec()
    try:
        results = {repo.name: reconcile_repo(repo, spec) for repo in args.repos}
    except DecisionFileError as exc:
        print(f"reconcile.py: error: {exc}", file=sys.stderr)
        return 2

    if args.json:
        print(json.dumps(results, indent=2, sort_keys=True))
        return 0

    for name, r in results.items():
        if not r["applicable"]:
            print(f"\n{name}: not applicable (does not vendor the py-lmdb fork)")
            continue
        n_d = len(r["decisions_required"])
        print(f"\n{name}: 0 change(s), {n_d} stop(s) [{r['digest'][:12]}]")
        for d in r["decisions_required"]:
            print(f"  ? {d['type']} {d['path']}: {d['question']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

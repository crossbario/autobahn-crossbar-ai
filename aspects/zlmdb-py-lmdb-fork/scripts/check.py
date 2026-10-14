###############################################################################
#
#  Copyright (C) typedef int GmbH
#  SPDX-License-Identifier: MIT
#
###############################################################################
"""Check zlmdb's py-lmdb fork against the pinned upstream baseline.

Standalone and stdlib-only (Python 3.11+); imports nothing from the fleet engine. It
reads the target tree (and its git objects, for submodule pins) and the aspect's own
``references/upstream-baseline.toml`` - no network, no upstream checkout - and reports
a finding per rule. See ``../SKILL.md``. Shared logic lives in ``_fork.py`` so this
agrees with ``reconcile.py``.

Usage::

    python check.py <repo> [<repo> ...]
    python check.py --json <repo> [<repo> ...]

Exit code: 0 if no rule FAILs (WARN allowed), 1 if any repo FAILs, 2 on usage error.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

from _fork import (
    ASPECT,
    DecisionFileError,
    Spec,
    applicable,
    canonical_sha256,
    current_decision,
    deviations,
    drift,
    load_spec,
    open_decision_files,
)

OK = "OK"
WARN = "WARN"
FAIL = "FAIL"


@dataclass(frozen=True)
class Finding:
    """One rule's verdict for one repository."""

    rule: str
    status: str
    message: str


def _check_forked_from(found: list[dict]) -> Finding:
    for d in found:
        if d["what"] == "py-lmdb":
            return Finding(
                "forked-from",
                FAIL,
                f"{d['path']}: py-lmdb {d['observed']} (baseline {d['expected']})",
            )
    return Finding("forked-from", OK, "at the baseline's py-lmdb version")


def _check_pins(found: list[dict], spec: Spec) -> Finding:
    bad = [d for d in found if d["what"] != "py-lmdb"]
    if bad:
        detail = "; ".join(
            f"{d['path']}: {d['observed'] or 'no gitlink'} (baseline {d['expected']})"
            for d in bad
        )
        return Finding("lmdb-pins", FAIL, detail)
    tags = ", ".join(e.tag for e in spec.engines)
    return Finding("lmdb-pins", OK, f"pinned to {tags}")


def _check_deviations(repo: Path, found: list[dict]) -> Finding:
    if not found:
        return Finding("deviations", OK, "patch series and test cases match upstream")
    try:
        decided = current_decision(repo)
    except DecisionFileError as exc:
        return Finding("deviations", FAIL, f"untrustworthy decision file: {exc}")
    summary = f"{len(found)} difference(s) from upstream"
    if decided is not None:
        path, decision = decided
        if decision["precondition"]["sha256"] == canonical_sha256(found):
            where = f".decisions/{ASPECT}/{path.name}"
            if decision["answer"] == "accept":
                return Finding("deviations", WARN, f"{summary}, accepted in {where}")
            return Finding("deviations", FAIL, f"{summary}, to port ({where})")
    stale = " (the recorded decision is stale: re-decide)" if decided else ""
    return Finding(
        "deviations", FAIL, f"{summary} - a signed decision is required{stale}"
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


def inspect_repo(repo: Path, spec: Spec) -> list[Finding]:
    """Return the findings for ``repo``."""
    if not applicable(repo, spec):
        return [Finding("fork", FAIL, f"no {spec.vendor_init}: not the zlmdb fork")]
    found = drift(repo, spec)
    return [
        _check_forked_from(found),
        _check_pins(found, spec),
        _check_deviations(repo, deviations(repo, spec)),
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
        description="Check zlmdb's py-lmdb fork against the upstream baseline."
    )
    parser.add_argument(
        "repos", nargs="+", type=Path, help="repository directories to check"
    )
    parser.add_argument("--json", action="store_true", help="emit findings as JSON")
    args = parser.parse_args(argv)

    spec = load_spec()
    results = {repo.name: inspect_repo(repo, spec) for repo in args.repos}

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

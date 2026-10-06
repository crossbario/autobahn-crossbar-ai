---
name: python-package
description: >-
  The Autobahn-Crossbar.io house standard for a Python package. Checks (and, via rollout,
  reconciles) a repository's pyproject build backend, CalVer version, Python
  floor, license and source headers. Use when onboarding
  or auditing a Python package in the estate, or when asked whether a repo follows
  the house Python-package pattern.
---

# Python Package aspect

A repository carries this aspect when it is a Python package that must follow the
estate's house standard. The aspect is **defined once here** (in
`autobahn-crossbar-ai`) and applied to every package that lists `python-package`
among its aspects — the WAMP packages first (`txaio`, `autobahn-python`,
`crossbar`, `zlmdb`, `cfxdb`, `wamp-xbr`) with the license value the only thing that
differs per package.

## What "compliant" means

The rules, in full, are in [`references/house-standard.md`](references/house-standard.md);
the machine-readable form is [`aspect.toml`](aspect.toml). In short, a compliant
package's `pyproject.toml` has:

- **Build backend `hatchling.build`** (`requires = ["hatchling"]`); `setuptools`
  only where a package *imports* it at build time (cffi's `ffi.verify`), never as
  the backend.
- **CalVer `YY.M.MICRO` with MICRO ≥ 1** (never `.0`; `.devN` suffix allowed).
- **`requires-python >= 3.11`**, CPython + PyPy classifiers.
- **A PEP 639 `license`** — `MIT` or `EUPL-1.2` for the OSS packages, a proprietary SPDX
  expression (`LicenseRef-Proprietary`) for closed source ones. The value is per-repo;
  the aspect does not fork.
- **An SPDX / copyright header** on every *non-generated* source file. Generated code is
  exempt by *tree*, not just per file: a marker (`automatically generated` / `do not
  modify` / `@generated`) in the file head, **or** an *empty* `__init__.py` living in a
  generated directory tree (the package init a generator emits). A *content-bearing*
  `__init__.py` is hand-written and gets a header even inside a generated tree; a genuine
  empty `__init__.py` outside any generated tree gets one too.

Lint (`ruff`), types (`ty`) and tests (`pytest`) are **preliminary and parked** in
[`.parked/`](.parked/) — not yet active, so the checker does not enforce them.

## Inspect (check) — available now

`scripts/check.py` reads a repo's `pyproject.toml` and reports a finding per rule
(`OK` / `WARN` / `FAIL`). It is standalone and stdlib-only (Python 3.11+), imports
nothing from the fleet engine, and exits non-zero only on a hard `FAIL`:

```bash
python aspects/python-package/scripts/check.py <repo> [<repo> ...]
python aspects/python-package/scripts/check.py --json <repo>
```

`FAIL` is reserved for the load-bearing rules (no `pyproject.toml`, wrong build
backend, non-CalVer or `.0` version, a Python floor below 3.11). The softer rules
(a missing `license` string, missing source headers) are `WARN`: they are the house
pattern, but a legacy package is brought up to them by a **rollout**, not failed outright.

## Reconcile (rollout) — forthcoming

`scripts/reconcile.py` will emit the changes that bring a package toward the
standard. Reconciliation is **deterministic given its inputs** and surfaces the
genuinely ambiguous cases as typed decisions rather than silent rewrites — per the
fleet reconciler and assurance axiom `A18`. The engine applies the resulting change
set; this aspect only *computes* it.

## Edge cases and decisions

- **License.** OSS (`MIT`, `EUPL-1.2`) vs proprietary (`LicenseRef-Proprietary`)
  is a per-repo value; a package with a deliberately different license is a decision,
  not a failure.
- **setuptools.** A package that legitimately needs `setuptools` as a *dependency*
  (`cffi`) is compliant; only `setuptools` as the *build backend* is a failure.

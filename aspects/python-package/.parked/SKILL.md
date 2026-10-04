---
name: python-package
description: >-
  The AAIARE house standard for a Python package. Checks (and, via rollout,
  reconciles) a repository's pyproject build backend, CalVer version, Python
  floor, license, lint/type/test tooling and source headers. Use when onboarding
  or auditing a Python package in the estate, or when asked whether a repo follows
  the house Python-package pattern.
---

# Python Package aspect

A repository carries this aspect when it is a Python package that must follow the
estate's house standard. The aspect is **defined once here** (in
`autobahn-crossbar-ai`) and applied to every package that lists `python-package`
among its aspects — the WAMP packages first (`txaio`, `autobahn-python`,
`crossbar`, `zlmdb`, `cfxdb`, `wamp-xbr`, `py-lmdb`), and the aaiare packages
later, with the license value the only thing that differs per package.

## What "compliant" means

The rules, in full, are in [`references/house-standard.md`](references/house-standard.md);
the machine-readable form is [`aspect.toml`](aspect.toml). In short, a compliant
package's `pyproject.toml` has:

- **Build backend `hatchling.build`** (`requires = ["hatchling"]`); `setuptools`
  only where a package *imports* it at build time (cffi's `ffi.verify`), never as
  the backend.
- **CalVer `YY.M.MICRO` with MICRO ≥ 1** (never `.0`; `.devN` suffix allowed).
- **`requires-python >= 3.11`**, CPython + PyPy classifiers.
- **A PEP 639 `license`** — `MIT` for the OSS packages, a proprietary SPDX
  expression (`LicenseRef-Proprietary`) for the closed ones. The value is per-repo;
  the aspect does not fork.
- **`[tool.ruff]`** (new code: `select = ["ALL"]`), **`[tool.ty]`**,
  **`[tool.pytest.ini_options]`**.
- **An SPDX / copyright header** on every source file.

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
(`ruff select=ALL`, `ty`, `pytest`, headers, a missing license string) are `WARN`:
they are the house pattern, but a legacy package is brought up to them by a
**rollout**, not failed outright.

## Reconcile (rollout) — forthcoming

`scripts/reconcile.py` will emit the changes that bring a package toward the
standard (add a `[tool.ty]` block, raise `ruff` to `select = ["ALL"]`, add missing
headers, …). Reconciliation is **deterministic given its inputs** and surfaces the
genuinely ambiguous cases as typed decisions rather than silent rewrites — per the
fleet reconciler and assurance axiom A18. The engine applies the resulting change
set; this aspect only *computes* it.

## Edge cases and decisions

- **Legacy vs new code.** Existing packages use a narrower `ruff` select
  (`E4/E7/E9/F`); the house standard for *new* code is `select = ["ALL"]`. Raising
  a legacy package to `ALL` surfaces real lint debt — a decision (raise now, or
  stage), not an automatic rewrite.
- **License.** OSS (`MIT`) vs proprietary (`LicenseRef-Proprietary`) is a per-repo
  value; a package with a deliberately different license (e.g. `crossbar` is
  `EUPL-1.2`) is a decision, not a failure.
- **setuptools.** A package that legitimately needs `setuptools` as a *dependency*
  (cffi) is compliant; only `setuptools` as the *build backend* is a failure.

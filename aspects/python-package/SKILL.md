---
name: python-package
description: >-
  The Autobahn-Crossbar.io house standard for a Python package. Checks (and, via rollout,
  reconciles) a repository's pyproject build backend, CalVer version, Python
  floor, license (a deviation is a signed decision), source headers and that
  submodules are excluded from linting. Use when onboarding
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
- **A PEP 639 `license`** — `MIT` for the OSS packages, `LicenseRef-Proprietary` for
  closed source ones. Any other license (crossbar's `EUPL-1.2`, for one) is a legitimate
  per-repo choice but a **deviation**: it needs a signed decision in the target (see
  *Decisions* below). The aspect does not fork per license.
- **Submodules excluded from linting** — where the package configures ruff, every path in
  `.gitmodules` is in the top-level `[tool.ruff]` `extend-exclude` (or `exclude`), so a
  checked-out submodule (`.ai`, `.cicd`, a pinned aspect repository) is never linted or
  formatted as this package's code. A `[tool.ruff.lint]` exclude is not enough: it still
  lets `ruff format` in.
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
backend, non-CalVer or `.0` version, a Python floor below 3.11, a submodule ruff would
lint as package code, an untrustworthy decision file). The softer rules
(a missing `license` string, missing source headers) are `WARN`: they are the house
pattern, but a legacy package is brought up to them by a **rollout**, not failed outright.

## Reconcile (rollout)

`scripts/reconcile.py` emits the ChangeSet that brings a package to the standard:
headers for unheadered non-generated sources, and the missing ruff excludes. It is
standalone and stdlib-only, changes nothing itself, and is **deterministic given its
inputs** — the same repository and decision files give byte-identical JSON and digest.
The genuinely ambiguous cases surface as typed decisions rather than silent rewrites,
per assurance axiom `A18`; the engine applies the ChangeSet, this aspect only *computes*
it.

```bash
python aspects/python-package/scripts/reconcile.py [--json] <repo> [<repo> ...]
```

A repository without `pyproject.toml` is **not applicable** (`"applicable": false`): an
empty ChangeSet and no question — not a decision.

## Decisions (A18)

A decision is signed data **in the target**, read by `reconcile.py` from
`.decisions/python-package/<YYYYMMDD>-<type>[-N].toml` (the convention of
`fleet-and-aspect-governance.md` §5):

- **One new file per answer**, add-only; each later file names its predecessor in
  `supersedes`. The **newest** file (by date, then `-N`) is the current decision — an
  older one is history, never a fallback.
- Every file binds a **precondition**: the sha256 of exactly what was observed when the
  question was answered. If the repository has changed since, the request is re-raised;
  an old answer is never applied to a changed repository.
- A file that cannot be trusted as written — not TOML, another aspect or type, an answer
  outside its options, a licensing answer not `decided_by = "human"`, no precondition, a
  broken `supersedes` chain — is an **error**, never silently skipped.
- Verifying the decision commit's **signature** is the fleet driver's job before it
  resumes (fail closed); this aspect reads files.

The one decision type today is **`license_deviation`**: a license outside `MIT` /
`LicenseRef-Proprietary`. Options `keep` (headers use the declared license) and
`relicense:MIT`. Relicensing is a legal act the aspect never performs: after that answer
the reconcile stays stopped (`license_relicense_pending`) until the maintainer's own
relicensing change lands. The precondition covers `[project].license` and the `LICENSE`
file's sha256.

## Edge cases and decisions

- **License.** `MIT` (OSS) or `LicenseRef-Proprietary` (closed) is the house value; a
  package with a deliberately different license (`EUPL-1.2`) is a signed decision, not a
  failure — and not silently accepted either.
- **setuptools.** A package that legitimately needs `setuptools` as a *dependency*
  (`cffi`) is compliant; only `setuptools` as the *build backend* is a failure.

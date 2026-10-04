# The AAIARE Python-package house standard

The rules the `python-package` aspect checks and reconciles. The reference
implementation is `txaio` (the cleanest pure-Python package); the cffi packages
(`autobahn-python`, `zlmdb`, `crossbar`, `py-lmdb`) are the extension cases.

Severity: **FAIL** = load-bearing (the package is not the house pattern); **WARN** =
house pattern, raised by a rollout rather than failed on a legacy package.

## Build system — FAIL

```toml
[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"
```

`hatchling` is the house backend, universally. `setuptools` is **not** a build
backend here; it appears only in `requires` / runtime deps where a package *imports*
it (cffi's `ffi.verify()` on Python ≥ 3.12). "Needs setuptools as a dep" is not
"uses setuptools as the backend".

## Version — FAIL

CalVer `YY.M.MICRO` with **MICRO ≥ 1** (never `.0`); a `.devN` suffix is allowed
(e.g. `26.9.1`, `26.10.1.dev1`).

## Python floor — FAIL

`requires-python = ">=3.11"` (or higher). Classifiers list CPython + PyPy and the
supported minors (3.11–3.14).

## License — WARN (presence) / per-repo value

A single PEP 639 expression, no `License ::` classifier:

- OSS packages: `license = "MIT"`.
- Closed packages: `license = "LicenseRef-Proprietary"` + `license-files = ["LICENSE"]`.

The value differs per package and is a decision, not a fork of the aspect. A
deliberately different OSS license (e.g. `crossbar` is `EUPL-1.2`) is a decision.

## Lint / format — WARN

```toml
[tool.ruff]
line-length = 88
target-version = "py311"
extend-exclude = [".ai", ".cicd"]   # and .deps for a deps-flavor repo

[tool.ruff.lint]
select = ["ALL"]        # NEW code; legacy packages use E4/E7/E9/F and warn until raised

[tool.ruff.format]
quote-style = "double"

[tool.ruff.lint.pydocstyle]
convention = "google"
```

## Types — WARN

```toml
[tool.ty]
[tool.ty.rules]
```

`ty` (Astral's type checker) is the house type checker.

## Tests — WARN

```toml
[tool.pytest.ini_options]
testpaths = ["tests"]
addopts = ["--strict-markers", "--strict-config"]
```

`coverage` config alongside.

## Source headers — WARN

Every source file carries a copyright / SPDX header:

```python
# Copyright (c) typedef int GmbH, Germany, <year>. All rights reserved.
# SPDX-License-Identifier: MIT              # or LicenseRef-Proprietary for closed packages
```

## Environment / runner

`uv` + `.venv` + a `justfile` with the standard recipe set
(`create` / `install` / `install-dev` / `install-tools` / `test` / `check`, per
Python-version venvs `cpy311..cpy314` / `pypy311`). `nox` is emerging, not yet
required.

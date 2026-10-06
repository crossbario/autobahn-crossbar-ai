# The AAIARE Python-package house standard

The rules the `python-package` aspect checks and reconciles. The reference
implementation is `txaio` (the cleanest pure-Python package); the `cffi` packages
(`autobahn-python`, `zlmdb`) are the extension cases.

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

`requires-python = ">=3.11"`. Classifiers list CPython + PyPy and the
supported minors (3.11–3.14). PyPy is a first-class citizen! Python 3.15 is emerging,
not yet required.

## License — WARN (presence) / per-repo value

A single PEP 639 expression, no `License ::` classifier:

- OSS packages: `license = "MIT"`.
- Closed packages: `license = "LicenseRef-Proprietary"` + `license-files = ["LICENSE"]`.

The value differs per package and is a decision, not a fork of the aspect. A
deliberately different license (OSS or other) is a decision.

## Source headers — WARN

Every **non-generated** source file carries a copyright with SPDX header. Generated
code is **exempt** — the generator owns its header. "Generated" is a *tree*, not just a
per-file marker: a file is exempt if it carries a marker in its head (`automatically
generated` / `do not modify` / `@generated`, e.g. FlatBuffers output) **or** it is an
*empty* `__init__.py` inside a generated directory tree — a directory whose subtree
contains marker-bearing files and no hand-written file (a `.py` that is neither
marker-bearing nor an empty `__init__.py`). This catches the empty package `__init__.py` a
generator emits alongside its marked output (flatc literally `touch`es them); a header on
those would be stripped by a clean regenerate (= drift, which a clean-regenerate CI check
rejects). A **content-bearing** `__init__.py` is hand-written and **gets a header** even
inside a generated tree; a genuine empty `__init__.py` outside any generated tree (a test
or package marker) also gets one. The header:

```python
###############################################################################
#
#  Copyright (C) typedef int GmbH
#  SPDX-License-Identifier: MIT
#
###############################################################################
```

or

```python
###############################################################################
#
#  Copyright (C) typedef int GmbH
#  SPDX-License-Identifier: EUPL-1.2
#
###############################################################################
```

or

```python
###############################################################################
#
#  Copyright (C) typedef int GmbH (Germany). All rights reserved.
#  SPDX-License-Identifier: LicenseRef-Proprietary
#
###############################################################################
```

Drop a year or range of years completely (follow "Modern FSFE / Linux Foundation / Tech Practice")!

## Environment / runner

`uv` + `.venvs` + a `justfile` with the standard recipe set

1. *none* (list recipes)
2. `create`
3. `install`
4. `install-dev`
5. `install-tools`
6. `clean-build`
7. `distclean`
8. `test`
9. `check`

per Python-version venvs `cpy311..cpy314` / `pypy311`. `cpy315` is emerging, not yet required.

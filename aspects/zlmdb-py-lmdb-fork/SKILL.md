---
name: zlmdb-py-lmdb-fork
description: >-
  Keeps zlmdb's vendored, CFFI-only fork of py-lmdb (and the LMDB sources it bundles,
  both release lines 0.9.x and 1.0.x) in sync with upstream. Checks the fork against a
  pinned upstream baseline (py-lmdb version, LMDB tags, patch series, upstream test
  cases), and describes how to bring it in sync when upstream moves. Use when auditing
  zlmdb's LMDB layer, when asked whether zlmdb is behind py-lmdb or LMDB, or when
  porting a new py-lmdb release into zlmdb.
---

# zlmdb py-lmdb fork aspect

zlmdb vendors LMDB and a fork of [py-lmdb](https://github.com/jnwatson/py-lmdb), so it
can ship its own CFFI-only wheels for CPython **and PyPy** on every platform it
supports, without depending on distro packages (see crossbario/zlmdb#111). The cost of
that is keeping the fork in sync. This aspect makes falling behind visible, and
describes the port.

The aspect applies to one repository, zlmdb. Its definition is split in two:

- [`aspect.toml`](aspect.toml) `[target]`: where zlmdb keeps the fork (the vendored
  package, the LMDB submodules, the patch directories, the vendored tests);
- [`references/upstream-baseline.toml`](references/upstream-baseline.toml): the upstream
  state the fork must match. It is **generated** by `scripts/upstream_watch.py --write`
  from upstream git checkouts and never edited by hand.

## What "compliant" means

| rule | the fork must | else |
|---|---|---|
| `forked-from` | declare `__forked_from__ = 'py-lmdb <baseline version>'` | FAIL |
| `lmdb-pins` | pin each LMDB submodule (in `HEAD`) to the baseline tag's commit: `lmdb-upstream` (0.9.x), `lmdb-upstream-1.0` (1.0.x) | FAIL |
| `deviations` | vendor each engine's patch series byte-identical to upstream's (`lib/py-lmdb/`, `lib1/py-lmdb/`), and carry every upstream test case in its vendored tests | FAIL, unless a current signed decision accepts the differences (then WARN) |
| `open-decisions` | have no `.decisions/zlmdb-py-lmdb-fork/OPEN-*.toml` | FAIL |

A test case counts as present when a `def test_<name>(` of the same name is in the
vendored module of the same file name; zlmdb's own extra tests are fine.

## Inspect (check)

`scripts/check.py` reads the target tree, the target's git objects (for submodule pins)
and the aspect's baseline. It needs no network and no upstream checkout, so it gives
the same answer on every host for the same commit:

```bash
python aspects/zlmdb-py-lmdb-fork/scripts/check.py <zlmdb>
python aspects/zlmdb-py-lmdb-fork/scripts/check.py --json <zlmdb>
```

Exit code 0 when nothing FAILs, 1 otherwise.

## Reconcile (rollout)

`scripts/reconcile.py <target> --json` has the same interface and result shape as the
other aspects' (`applicable`, `changeset`, `decisions_required`, `digest`; canonical,
no timestamps). Its `changeset` is always **empty**: a port is not a file operation.
What it reports is what stops the rollout:

- `port_required`: the fork is not at the baseline's py-lmdb version or an LMDB tag.
  Not a decision: the rollout stays stopped until the port has landed.
- `baseline_deviation`: differences from upstream's patch series or test cases that
  no current decision covers. A decision request (A18), options `accept` / `port`,
  `decided_by = human`, bound to the sha256 of exactly the observed differences.
- `port_pending`: the differences were decided `port`, and are still there.

A target without `src/zlmdb/_lmdb_vendor/__init__.py` is **not applicable**.

## Decisions (A18)

A decision is signed data in the target, read from
`.decisions/zlmdb-py-lmdb-fork/<YYYYMMDD>-baseline_deviation[-N].toml`:

```toml
schema     = 1
aspect     = "zlmdb-py-lmdb-fork"
type       = "baseline_deviation"
options    = ["accept", "port"]
answer     = "accept"
decided_by = "human"
reason     = "CFFI-only: no CPython C extension, so lib/py-lmdb/rename.h is not vendored"
supersedes = "20261020-baseline_deviation.toml"   # the previous file; omit for the first

[precondition]
sha256 = "<the precondition sha256 from reconcile.py's decision request>"
```

- One new file per answer, add-only. The **newest** file is the current decision; each
  later file names its predecessor in `supersedes`.
- The precondition covers exactly the observed differences. Any change to them - a
  patch fixed, a new upstream test - re-raises the request; an old answer is never
  applied to a changed fork.
- A file that cannot be trusted as written (not TOML, wrong aspect or type, an answer
  outside its options, not `decided_by = "human"`, no precondition, a broken
  `supersedes` chain) is an error, never skipped.
- Decisions are signed by the maintainer. Verifying the signature of the decision commit
  is the fleet driver's job; this aspect reads files.

## Watch upstream, bump the baseline

`scripts/upstream_watch.py` is the only part that looks at upstream, and it is not part
of the check. It needs local git checkouts and never fetches:

```bash
git clone https://github.com/jnwatson/py-lmdb.git     # or: git -C py-lmdb fetch --tags
git clone --bare https://github.com/LMDB/lmdb.git     # LMDB_x.y.z tags, both lines
python aspects/zlmdb-py-lmdb-fork/scripts/upstream_watch.py --py-lmdb py-lmdb --lmdb lmdb.git
```

It compares the newest `py-lmdb_X.Y.Z` release (or `--tag`) with the pinned baseline and
exits 1 when they differ, listing what changed: the py-lmdb version, LMDB tags, patch
files added / removed / changed, new or removed test cases. `--write` regenerates the
baseline from that release. A baseline bump is a change to this aspect, reviewed and
landed like any other, followed by its own rollout.

## Port: bring the fork in sync

Once the baseline is bumped, `check.py` goes red on zlmdb. Port in zlmdb, test-first,
one cause per pushed step:

1. **Baseline:** a no-op change (the branch's audit file) must be green on CI.
2. **Harness**, if the new tests need it, with the old tests: must stay green.
3. **Tests only:** vendor upstream's tests for the new release into
   `src/zlmdb/tests/lmdb/` (keeping zlmdb's import adaptations: `import lmdb` ->
   `import zlmdb.lmdb as lmdb`, `import testlib` -> `from . import testlib`, `lmdb.cffi`
   / `lmdb.tool` / `lmdb.aio` -> `zlmdb._lmdb_vendor.*`). Must go red.
4. **Fix only:** bump the LMDB submodules, replace the patch series, port the binding
   (`src/zlmdb/_lmdb_vendor/`, CFFI only), set `__forked_from__`. The same tests must
   go green, on CPython and PyPy.

Then `check.py` on the landed zlmdb is green, or WARN for accepted deviations.

## Known traps

- **Crashing tests.** Upstream's newer tests can segfault or deadlock against the old
  fork. zlmdb runs them with `pytest --forked --timeout ... -o timeout_func_only=true`
  (`just test-lmdb`): without `timeout_func_only`, pytest-timeout's timer runs in the
  parent process and a timeout ends the whole session.
- **Stale LMDB sources.** zlmdb's editable install prepares the patched LMDB sources in
  `build/lmdb-src` only when that directory is missing; after changing patches or
  submodules, remove it.
- **PyPy wheel cache.** The `pp73` wheel tag is shared across PyPy point releases; a
  wheel cached for an older PyPy can fail to import on a newer one
  (`pip cache remove <pkg>` or `--no-cache-dir`).
- **Stale venvs.** `just create` keeps an existing venv even when its interpreter no
  longer matches the pin; recreate it after an interpreter update.
- **uv on ZFS.** uv's clone link mode can fail with `EAGAIN` (os error 11) on ZFS; set
  `UV_LINK_MODE=copy`.

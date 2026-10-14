###############################################################################
#
#  Copyright (C) typedef int GmbH
#  SPDX-License-Identifier: MIT
#
###############################################################################
"""zlmdb-py-lmdb-fork: check, reconcile, decisions and the upstream watcher.

The fixtures are small git repositories built in a temp dir: a fork layout (vendored
init, LMDB submodule gitlinks, patch directories, vendored tests) checked against a
small baseline of the same shape as ``references/upstream-baseline.toml``.

The aspect's scripts share their module names with python-package's (``check``,
``reconcile``), so they are loaded here under their own names.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).parents[1] / "aspects" / "zlmdb-py-lmdb-fork" / "scripts"
sys.path.insert(0, str(SCRIPTS))

import _fork  # noqa: E402


def _load(name: str):
    spec = importlib.util.spec_from_file_location(
        f"fork_{name}", SCRIPTS / f"{name}.py"
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module  # dataclasses look their module up there
    spec.loader.exec_module(module)
    return module


check = _load("check")
reconcile = _load("reconcile")
watch = _load("upstream_watch")

EMPTY_DIGEST = "4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945"
LIB_COMMIT = "1" * 40
LIB1_COMMIT = "2" * 40
PATCHES = {
    "lib": {"a.patch": "patch a\n", "PATCH-STATUS.md": "status\n"},
    "lib1": {"a.patch": "patch a (1.0)\n", "rename.h": "#define x y\n"},
}
TESTS = {"cve_test.py": ["test_one", "test_two"]}
TESTS_SRC = (
    "class T:\n"
    "    def test_one(self):\n        pass\n\n"
    "    def test_two(self):\n        pass\n"
)


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args],  # noqa: S607
        capture_output=True,
        text=True,
        check=True,
        env={
            "GIT_AUTHOR_NAME": "t",
            "GIT_AUTHOR_EMAIL": "t@example.invalid",
            "GIT_COMMITTER_NAME": "t",
            "GIT_COMMITTER_EMAIL": "t@example.invalid",
            "GIT_CONFIG_GLOBAL": "/dev/null",
            "GIT_CONFIG_SYSTEM": "/dev/null",
            "PATH": "/usr/bin:/bin",
        },
    ).stdout


@pytest.fixture
def spec(tmp_path):
    """A small baseline (py-lmdb 3.0.0) loaded with the aspect's real target layout."""
    lines = [
        "schema = 1",
        "[py-lmdb]",
        'version = "3.0.0"',
        'tag = "py-lmdb_3.0.0"',
        f'commit = "{"9" * 40}"',
        "[lmdb.lib]",
        'tag = "LMDB_0.9.36"',
        f'commit = "{LIB_COMMIT}"',
        "[lmdb.lib1]",
        'tag = "LMDB_1.0.2"',
        f'commit = "{LIB1_COMMIT}"',
    ]
    for tree, files in PATCHES.items():
        lines.append(f"[patches.{tree}]")
        lines += [f'"{name}" = "{_sha(text)}"' for name, text in files.items()]
    for module, cases in TESTS.items():
        lines += [f'[tests."{module}"]', f"cases = {json.dumps(cases)}"]
    path = tmp_path / "baseline.toml"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return _fork.load_spec(path)


def make_fork(
    root: Path,
    *,
    version: str = "3.0.0",
    pins: dict[str, str] | None = None,
    patches: dict[str, dict[str, str]] | None = None,
    tests_src: str = TESTS_SRC,
) -> Path:
    """A zlmdb-like repository at the baseline, unless told otherwise."""
    repo = root / "zlmdb"
    vendor = repo / "src/zlmdb/_lmdb_vendor"
    vendor.mkdir(parents=True)
    (vendor / "__init__.py").write_text(
        f"__forked_from__ = 'py-lmdb {version}'\n", encoding="utf-8"
    )
    tests = repo / "src/zlmdb/tests/lmdb"
    tests.mkdir(parents=True)
    (tests / "cve_test.py").write_text(tests_src, encoding="utf-8")
    dirs = {"lib": "lmdb-patches", "lib1": "lmdb-patches-1.0"}
    for tree, files in (PATCHES if patches is None else patches).items():
        (repo / dirs[tree]).mkdir()
        for name, text in files.items():
            (repo / dirs[tree] / name).write_text(text, encoding="utf-8")
    _git(repo, "init", "-q")
    pins = {"lmdb-upstream": LIB_COMMIT, "lmdb-upstream-1.0": LIB1_COMMIT} | (
        pins or {}
    )
    for path, commit in pins.items():
        if commit:
            _git(
                repo, "update-index", "--add", "--cacheinfo", f"160000,{commit},{path}"
            )
    _git(repo, "add", "src", *[d for d in dirs.values() if (repo / d).exists()])
    _git(repo, "commit", "-q", "-m", "fork")
    return repo


def decide(repo: Path, answer: str, sha256: str, name: str = "20261020", **extra):
    folder = repo / ".decisions" / _fork.ASPECT
    folder.mkdir(parents=True, exist_ok=True)
    fields = {
        "schema": 1,
        "aspect": _fork.ASPECT,
        "type": _fork.DEVIATION,
        "options": list(_fork.DEVIATION_OPTIONS),
        "answer": answer,
        "decided_by": "human",
    } | extra
    body = "".join(f"{k} = {json.dumps(v)}\n" for k, v in fields.items())
    body += f'[precondition]\nsha256 = "{sha256}"\n'
    path = folder / f"{name}-{_fork.DEVIATION}.toml"
    path.write_text(body, encoding="utf-8")
    return path


def statuses(repo: Path, spec) -> dict[str, str]:
    return {f.rule: f.status for f in check.inspect_repo(repo, spec)}


# --- check + reconcile -------------------------------------------------------------


def test_converged_fork(tmp_path, spec):
    repo = make_fork(tmp_path)
    assert set(statuses(repo, spec).values()) == {"OK"}
    result = reconcile.reconcile_repo(repo, spec)
    assert result == {
        "applicable": True,
        "changeset": [],
        "decisions_required": [],
        "digest": EMPTY_DIGEST,
    }


def test_behind_upstream_is_a_port_not_a_decision(tmp_path, spec):
    repo = make_fork(tmp_path, version="2.2.1", pins={"lmdb-upstream": "3" * 40})
    got = statuses(repo, spec)
    assert got["forked-from"] == "FAIL"
    assert got["lmdb-pins"] == "FAIL"
    stops = reconcile.reconcile_repo(repo, spec)["decisions_required"]
    assert [(s["type"], s["path"]) for s in stops] == [
        ("port_required", "src/zlmdb/_lmdb_vendor/__init__.py"),
        ("port_required", "lmdb-upstream"),
    ]
    assert all("options" not in s for s in stops)


def test_missing_submodule_has_no_gitlink(tmp_path, spec):
    repo = make_fork(tmp_path, pins={"lmdb-upstream-1.0": ""})
    finding = next(f for f in check.inspect_repo(repo, spec) if f.rule == "lmdb-pins")
    assert finding.status == "FAIL"
    assert "lmdb-upstream-1.0: no gitlink" in finding.message


def test_deviations_listed_by_kind(tmp_path, spec):
    patches = {
        "lib": {"a.patch": "patch a, edited\n", "local.patch": "ours\n"},
        "lib1": PATCHES["lib1"],
    }
    repo = make_fork(tmp_path, patches=patches, tests_src="def test_one():\n    pass\n")
    assert _fork.deviations(repo, spec) == [
        {"kind": "patch_missing", "path": "lmdb-patches/PATCH-STATUS.md"},
        {"kind": "patch_changed", "path": "lmdb-patches/a.patch"},
        {"kind": "patch_added", "path": "lmdb-patches/local.patch"},
        {"kind": "test_missing", "path": "src/zlmdb/tests/lmdb/cve_test.py::test_two"},
    ]
    assert statuses(repo, spec)["deviations"] == "FAIL"
    (request,) = reconcile.reconcile_repo(repo, spec)["decisions_required"]
    assert request["type"] == "baseline_deviation"
    assert request["options"] == ["accept", "port"]
    assert request["precondition"]["sha256"] == _fork.canonical_sha256(
        request["observed"]
    )


def _cffi_only(tmp_path):
    patches = {"lib": PATCHES["lib"], "lib1": {"a.patch": PATCHES["lib1"]["a.patch"]}}
    return make_fork(tmp_path, patches=patches)


def test_accepted_deviation_is_a_warning_and_no_stop(tmp_path, spec):
    repo = _cffi_only(tmp_path)
    pre = _fork.canonical_sha256(_fork.deviations(repo, spec))
    decide(repo, "accept", pre, reason="CFFI-only: no rename.h")
    assert statuses(repo, spec)["deviations"] == "WARN"
    assert reconcile.reconcile_repo(repo, spec)["decisions_required"] == []


def test_port_answer_keeps_the_rollout_stopped(tmp_path, spec):
    repo = _cffi_only(tmp_path)
    decide(repo, "port", _fork.canonical_sha256(_fork.deviations(repo, spec)))
    assert statuses(repo, spec)["deviations"] == "FAIL"
    (stop,) = reconcile.reconcile_repo(repo, spec)["decisions_required"]
    assert stop["type"] == "port_pending"


def test_stale_decision_is_re_raised(tmp_path, spec):
    repo = _cffi_only(tmp_path)
    path = decide(repo, "accept", "0" * 64)
    finding = next(f for f in check.inspect_repo(repo, spec) if f.rule == "deviations")
    assert finding.status == "FAIL"
    assert "stale" in finding.message
    (request,) = reconcile.reconcile_repo(repo, spec)["decisions_required"]
    assert request["stale_decision"] == f".decisions/{_fork.ASPECT}/{path.name}"


def test_newest_decision_wins_and_the_chain_is_checked(tmp_path, spec):
    repo = _cffi_only(tmp_path)
    pre = _fork.canonical_sha256(_fork.deviations(repo, spec))
    first = decide(repo, "port", pre, name="20261020")
    decide(repo, "accept", pre, name="20261021", supersedes=first.name)
    assert statuses(repo, spec)["deviations"] == "WARN"
    decide(repo, "accept", pre, name="20261022")  # no supersedes: broken chain
    with pytest.raises(_fork.DecisionFileError, match="supersedes"):
        _fork.current_decision(repo)
    assert statuses(repo, spec)["deviations"] == "FAIL"


@pytest.mark.parametrize(
    ("answer", "extra", "problem"),
    [
        ("accept", {"decided_by": "agent"}, "decided_by"),
        ("ignore", {}, "unknown to this aspect"),
        ("accept", {"aspect": "python-package"}, "aspect"),
        ("accept", {"schema": 2}, "schema"),
    ],
)
def test_untrustworthy_decision_file(tmp_path, answer, extra, problem):
    repo = _cffi_only(tmp_path)
    decide(repo, answer, "a" * 64, **extra)
    with pytest.raises(_fork.DecisionFileError, match=problem):
        _fork.current_decision(repo)


def test_unreadable_decision_file(tmp_path):
    repo = _cffi_only(tmp_path)
    decide(repo, "accept", "a" * 64).write_text("not = [toml", encoding="utf-8")
    with pytest.raises(_fork.DecisionFileError, match="not a readable TOML"):
        _fork.current_decision(repo)


def test_open_decision_fails(tmp_path, spec):
    repo = make_fork(tmp_path)
    folder = repo / ".decisions" / _fork.ASPECT
    folder.mkdir(parents=True)
    (folder / "OPEN-1.toml").write_text('question = "accept?"\n', encoding="utf-8")
    finding = next(
        f for f in check.inspect_repo(repo, spec) if f.rule == "open-decisions"
    )
    assert finding.status == "FAIL"
    assert "accept?" in finding.message


def test_not_applicable(tmp_path, spec):
    (tmp_path / "other").mkdir()
    assert reconcile.reconcile_repo(tmp_path / "other", spec)["applicable"] is False
    assert statuses(tmp_path / "other", spec) == {"fork": "FAIL"}


# --- the scripts as the engine runs them (real baseline) ------------------------------


def _run(name: str, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(SCRIPTS / name), *args],
        capture_output=True,
        text=True,
        check=False,
    )


def test_reconcile_json_is_deterministic(tmp_path):
    repo = make_fork(tmp_path, version="2.2.1")
    first = _run("reconcile.py", str(repo), "--json")
    second = _run("reconcile.py", "--json", str(repo))
    assert first.returncode == 0
    assert first.stdout == second.stdout
    result = json.loads(first.stdout)["zlmdb"]
    assert result["changeset"] == []
    assert result["digest"] == EMPTY_DIGEST


def test_reconcile_stops_on_an_untrustworthy_decision(tmp_path):
    repo = make_fork(tmp_path)
    decide(repo, "accept", "a" * 64, decided_by="agent")
    proc = _run("reconcile.py", str(repo), "--json")
    assert proc.returncode == 2
    assert "decided_by" in proc.stderr


def test_check_exit_codes(tmp_path):
    repo = make_fork(tmp_path, version="2.2.1")
    proc = _run("check.py", str(repo))
    assert proc.returncode == 1
    assert "[FAIL] forked-from" in proc.stdout
    assert (
        json.loads(_run("check.py", "--json", str(repo)).stdout)["zlmdb"]["verdict"]
        == "FAIL"
    )


def test_real_baseline_loads():
    spec = _fork.load_spec()
    assert [e.key for e in spec.engines] == ["lib", "lib1"]
    assert all(len(e.commit) == 40 and e.files for e in spec.engines)
    assert spec.tests
    base = tomllib.loads(_fork.BASELINE.read_text(encoding="utf-8"))
    assert watch.render(base) == _fork.BASELINE.read_text(encoding="utf-8")


# --- upstream_watch -----------------------------------------------------------------


def _lmdb_h(major: int, minor: int, patch: int) -> str:
    return (
        f"#define MDB_VERSION_MAJOR\t{major}\n#define MDB_VERSION_MINOR\t{minor}\n"
        f"#define MDB_VERSION_PATCH\t{patch}\n"
    )


@pytest.fixture
def upstream(tmp_path):
    """Fake upstream checkouts: py-lmdb with two releases, LMDB with both tags."""
    lmdb = tmp_path / "lmdb"
    lmdb.mkdir()
    _git(lmdb, "init", "-q")
    for tag in ("LMDB_0.9.36", "LMDB_1.0.2"):
        _git(lmdb, "commit", "-q", "--allow-empty", "-m", tag)
        _git(lmdb, "tag", tag)
    py = tmp_path / "py-lmdb"
    files = {
        "lib/lmdb.h": _lmdb_h(0, 9, 36),
        "lib1/lmdb.h": _lmdb_h(1, 0, 2),
        "lib/py-lmdb/a.patch": "a\n",
        "lib1/py-lmdb/a.patch": "a1\n",
        "tests/cve_test.py": "def test_one():\n    pass\n",
        "tests/testlib.py": "def test_helper_not_a_module():\n    pass\n",
    }
    for rel, text in files.items():
        (py / rel).parent.mkdir(parents=True, exist_ok=True)
        (py / rel).write_text(text, encoding="utf-8")
    _git(py, "init", "-q")
    _git(py, "add", ".")
    _git(py, "commit", "-q", "-m", "9.0.0")
    _git(py, "tag", "py-lmdb_9.0.0")
    (py / "tests/cve_test.py").write_text(
        "def test_one():\n    pass\n\ndef test_new():\n    pass\n", encoding="utf-8"
    )
    _git(py, "commit", "-q", "-am", "10.0.0")
    _git(py, "tag", "py-lmdb_10.0.0")
    return py, lmdb


def test_newest_release_is_by_version(upstream):
    py, _ = upstream
    assert watch.newest_release(py) == "py-lmdb_10.0.0"


def test_upstream_baseline_render_round_trips(upstream):
    py, lmdb = upstream
    base = watch.upstream_baseline(py, lmdb, "py-lmdb_9.0.0")
    assert base["lmdb"]["lib"]["tag"] == "LMDB_0.9.36"
    assert (
        base["lmdb"]["lib1"]["commit"] == _git(lmdb, "rev-parse", "LMDB_1.0.2").strip()
    )
    assert base["patches"]["lib"] == {"a.patch": _sha("a\n")}
    assert base["tests"] == {"cve_test.py": {"cases": ["test_one"]}}
    parsed = tomllib.loads(watch.render(base))
    assert parsed["py-lmdb"] == base["py-lmdb"]
    assert parsed["patches"] == base["patches"]
    assert parsed["tests"] == base["tests"]


def test_compare_lists_what_upstream_changed(upstream):
    py, lmdb = upstream
    old = watch.upstream_baseline(py, lmdb, "py-lmdb_9.0.0")
    new = watch.upstream_baseline(py, lmdb, "py-lmdb_10.0.0")
    assert watch.compare(old, old) == []
    assert watch.compare(old, new) == [
        "py-lmdb 9.0.0 -> 10.0.0",
        "tests/cve_test.py: 1 new case(s)",
    ]

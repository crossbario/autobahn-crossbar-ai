###############################################################################
#
#  Copyright (C) typedef int GmbH
#  SPDX-License-Identifier: MIT
#
###############################################################################
"""A18 S2: the license value check, decision files, not-applicable, lint excludes."""

from __future__ import annotations

import json

import pytest
from check import FAIL, OK, WARN, inspect_repo
from conftest import GOOD_PYPROJECT, run_script
from reconcile import reconcile_repo

from _pp import (
    LICENSE_DEVIATION,
    DecisionFileError,
    canonical_sha256,
    current_decision,
    house_header,
    license_observation,
)

EUPL = GOOD_PYPROJECT.replace('license = "MIT"', 'license = "EUPL-1.2"')
EUPL_TEXT = "European Union Public Licence v. 1.2\n"


@pytest.fixture
def crossbar(package):
    """A package that deliberately deviates: EUPL-1.2, like crossbar."""
    return package(name="crossbar", **{"pyproject.toml": EUPL, "LICENSE": EUPL_TEXT})


def decide(repo, name, answer="keep", *, sha256=None, supersedes=None, **fields):
    """Write a decision file as the maintainer would (S3 renders and signs it)."""
    data = {
        "schema": 1,
        "aspect": "python-package",
        "provider": ".autobahn-crossbar-ai",
        "provider_rev": "77eb90baa33f76272b5472b2fe3b1592e00b830b",
        "type": LICENSE_DEVIATION,
        "question": "Keep EUPL-1.2?",
        "options": ["keep", "relicense:MIT"],
        "answer": answer,
        "decided_by": "human",
        **fields,
    }
    if supersedes is not None:
        data["supersedes"] = supersedes
    pre = sha256 or canonical_sha256(license_observation(repo))
    lines = [f"{k} = {json.dumps(v)}" for k, v in data.items()]
    lines += [
        "",
        "[precondition]",
        'paths = ["LICENSE", "pyproject.toml#project.license"]',
        f'sha256 = "{pre}"',
    ]
    folder = repo / ".decisions" / "python-package"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / name).write_text("\n".join(lines) + "\n", encoding="utf-8")


def _license(repo):
    (finding,) = [f for f in inspect_repo(repo) if f.rule == "license"]
    return finding


# -- the question --------------------------------------------------------------


def test_house_licenses_raise_nothing(package):
    for lic in ("MIT", "LicenseRef-Proprietary"):
        pp = GOOD_PYPROJECT.replace('license = "MIT"', f'license = "{lic}"')
        repo = package(name=lic.lower().replace("-", "_"), **{"pyproject.toml": pp})
        assert reconcile_repo(repo)["decisions_required"] == []


def test_a_deviation_raises_a_typed_human_only_request(crossbar):
    result = reconcile_repo(crossbar)
    assert result["changeset"] == []  # stops before any change
    (req,) = result["decisions_required"]
    assert req["type"] == LICENSE_DEVIATION
    assert req["options"] == ["keep", "relicense:MIT"]
    assert req["decided_by"] == ["human"]
    assert req["observed"]["pyproject.toml#project.license"] == "EUPL-1.2"
    assert req["precondition"]["sha256"] == canonical_sha256(
        license_observation(crossbar)
    )
    assert _license(crossbar).status == WARN
    assert "a signed decision is required" in _license(crossbar).message


def test_the_request_is_deterministic(crossbar):
    runs = [run_script("reconcile.py", "--json", str(crossbar)) for _ in range(2)]
    assert runs[0].returncode == 0
    assert runs[0].stdout == runs[1].stdout


# -- answered ------------------------------------------------------------------


def test_keep_proceeds_with_the_declared_license(crossbar):
    decide(crossbar, "20261008-license_deviation.toml")
    result = reconcile_repo(crossbar)
    assert result["decisions_required"] == []
    assert {op["license"] for op in result["changeset"]} == {"EUPL-1.2"}
    assert result["changeset"][0]["header"] == house_header("EUPL-1.2")
    assert "decided 'keep' in .decisions/python-package/20261008" in (
        _license(crossbar).message
    )


def test_relicense_is_never_performed_and_stays_stopped(crossbar):
    decide(crossbar, "20261008-license_deviation.toml", answer="relicense:MIT")
    result = reconcile_repo(crossbar)
    assert result["changeset"] == []
    (stop,) = result["decisions_required"]
    assert stop["type"] == "license_relicense_pending"
    assert stop["decision"].endswith("20261008-license_deviation.toml")


def test_a_changed_license_file_re_raises(crossbar):
    decide(crossbar, "20261008-license_deviation.toml")
    (crossbar / "LICENSE").write_text(EUPL_TEXT + "amended\n", encoding="utf-8")
    (req,) = reconcile_repo(crossbar)["decisions_required"]
    assert req["type"] == LICENSE_DEVIATION
    assert req["stale_decision"].endswith("20261008-license_deviation.toml")
    assert "stale" in _license(crossbar).message


def test_newest_wins_strictly_no_fallback(crossbar):
    decide(crossbar, "20261008-license_deviation.toml")  # matches today's state
    decide(
        crossbar,
        "20261009-license_deviation.toml",
        sha256="0" * 64,  # answered against another state
        supersedes="20261008-license_deviation.toml",
    )
    (req,) = reconcile_repo(crossbar)["decisions_required"]
    assert req["type"] == LICENSE_DEVIATION  # the older matching file is NOT used
    assert req["stale_decision"].endswith("20261009-license_deviation.toml")


def test_same_day_suffix_orders_after_the_first(crossbar):
    decide(crossbar, "20261008-license_deviation.toml", answer="relicense:MIT")
    decide(
        crossbar,
        "20261008-license_deviation-2.toml",
        supersedes="20261008-license_deviation.toml",
    )
    found = current_decision(crossbar, LICENSE_DEVIATION)
    assert found is not None
    path, data = found
    assert path.name == "20261008-license_deviation-2.toml"
    assert data["answer"] == "keep"


# -- untrustworthy decision files are errors, never defaults -------------------


@pytest.mark.parametrize(
    ("fields", "expect"),
    [
        ({"aspect": "other"}, "aspect 'other'"),
        ({"answer": "maybe"}, "is not one of"),
        ({"options": ["keep", "maybe"], "answer": "maybe"}, "unknown to this aspect"),
        ({"decided_by": "agent"}, "decided_by = 'human'"),
        ({"schema": 2}, "schema 2"),
    ],
)
def test_malformed_decision_files_are_refused(crossbar, fields, expect):
    answer = fields.pop("answer", "keep")
    decide(crossbar, "20261008-license_deviation.toml", answer=answer, **fields)
    with pytest.raises(DecisionFileError, match=expect):
        reconcile_repo(crossbar)
    assert _license(crossbar).status == FAIL
    proc = run_script("reconcile.py", str(crossbar))
    assert proc.returncode == 2
    assert proc.stderr.startswith("reconcile.py: error:")


def test_a_broken_supersedes_chain_is_refused(crossbar):
    decide(crossbar, "20261008-license_deviation.toml")
    decide(crossbar, "20261009-license_deviation.toml")  # does not name its predecessor
    with pytest.raises(DecisionFileError, match="supersedes None"):
        reconcile_repo(crossbar)


def test_a_decision_without_precondition_or_toml_is_refused(crossbar):
    decide(crossbar, "20261008-license_deviation.toml", sha256="not-a-sha")
    with pytest.raises(DecisionFileError, match="no \\[precondition\\] sha256"):
        reconcile_repo(crossbar)
    folder = crossbar / ".decisions" / "python-package"
    (folder / "20261008-license_deviation.toml").write_text("[broken", encoding="utf-8")
    with pytest.raises(DecisionFileError, match="not a readable TOML"):
        reconcile_repo(crossbar)


# -- not applicable ------------------------------------------------------------


def test_no_pyproject_is_not_applicable_not_a_question(package):
    site = package(name="site", **{"pyproject.toml": None, "LICENSE": "CC BY-SA 4.0\n"})
    result = reconcile_repo(site)
    assert result["applicable"] is False
    assert result["changeset"] == []
    assert result["decisions_required"] == []
    proc = run_script("reconcile.py", str(site))
    assert "site: not applicable (no pyproject.toml)" in proc.stdout


# -- submodules must not be linted as the package's code -----------------------

GITMODULES = """\
[submodule ".ai"]
\tpath = .ai
\turl = https://github.com/wamp-proto/wamp-ai.git
[submodule ".autobahn-crossbar-ai"]
\tpath = .autobahn-crossbar-ai
\turl = https://github.com/crossbario/autobahn-crossbar-ai.git
"""
RUFF = '\n[tool.ruff]\nextend-exclude = ["./.ai/"]\n'


def _excludes(repo):
    (finding,) = [f for f in inspect_repo(repo) if f.rule == "lint-excludes"]
    return finding


def test_unexcluded_submodule_fails_and_gets_an_op(package):
    repo = package(
        **{"pyproject.toml": GOOD_PYPROJECT + RUFF, ".gitmodules": GITMODULES}
    )
    assert _excludes(repo).status == FAIL
    assert ".autobahn-crossbar-ai" in _excludes(repo).message
    ops = [
        op for op in reconcile_repo(repo)["changeset"] if op["path"] == "pyproject.toml"
    ]
    assert ops == [
        {
            "kind": "file_modify",
            "path": "pyproject.toml",
            "action": "ruff_extend_exclude",
            "add": [".autobahn-crossbar-ai"],  # ./.ai/ already counts as .ai
        }
    ]


def test_every_submodule_excluded_passes(package):
    pp = GOOD_PYPROJECT + RUFF.replace('"./.ai/"', '".ai", ".autobahn-crossbar-ai"')
    repo = package(**{"pyproject.toml": pp, ".gitmodules": GITMODULES})
    assert _excludes(repo).status == OK
    assert all(
        op["path"] != "pyproject.toml" for op in reconcile_repo(repo)["changeset"]
    )


def test_no_ruff_config_requires_nothing(package):
    repo = package(**{".gitmodules": GITMODULES})
    assert _excludes(repo).status == OK
    assert "no [tool.ruff]" in _excludes(repo).message


@pytest.mark.parametrize(
    ("excludes", "missing"),
    [
        ('["deps"]', [".ai"]),  # a parent folder covers deps/flatbuffers
        ('["deps/*"]', [".ai"]),  # so does a glob
        ('["/deps/flatbuffers/", "./.ai"]', []),  # anchored + trailing slashes
        ('["deps/flat"]', [".ai", "deps/flatbuffers"]),  # a prefix is not a parent
    ],
)
def test_exclude_patterns_match_like_ruff(package, excludes, missing):
    gitmodules = (
        '[submodule ".ai"]\n\tpath = .ai\n\turl = x\n'
        '[submodule "deps/flatbuffers"]\n\tpath = deps/flatbuffers\n\turl = y\n'
    )
    pp = GOOD_PYPROJECT + f"\n[tool.ruff]\nextend-exclude = {excludes}\n"
    repo = package(**{"pyproject.toml": pp, ".gitmodules": gitmodules})
    ops = [
        op for op in reconcile_repo(repo)["changeset"] if op["path"] == "pyproject.toml"
    ]
    assert (ops[0]["add"] if ops else []) == missing


def test_lint_only_excludes_still_let_the_formatter_in(package):
    pp = GOOD_PYPROJECT + '\n[tool.ruff]\n\n[tool.ruff.lint]\nexclude = [".ai"]\n'
    gitmodules = '[submodule ".ai"]\n\tpath = .ai\n\turl = x\n'
    repo = package(**{"pyproject.toml": pp, ".gitmodules": gitmodules})
    assert _excludes(repo).status == FAIL

set shell := ["bash", "-uc"]
import? '.deps/wamp-cicd/workflow.just'

# --- the gate for this repository's own code ----------------------------------
# The aspect scripts are stdlib-only Python 3.11+; the tools are dev-only, pinned here
# and installed into .venvs/py<version> (the house .venvs pattern). Same recipe names
# as every repository.

RUFF := "ruff==0.16.10"
TY := "ty==0.0.84"
PYTEST := "pytest==9.1.1"

# Create/refresh the dev venv for a Python version (usage: `just venv 3.11`).
venv py="3.11":
    uv venv -q --allow-existing --python {{ py }} .venvs/py{{ py }}
    uv pip install -q --python .venvs/py{{ py }} {{ RUFF }} {{ TY }} {{ PYTEST }}

# Lint, format check and type check the aspect code and its tests.
check py="3.11": (venv py)
    .venvs/py{{ py }}/bin/ruff check .
    .venvs/py{{ py }}/bin/ruff format --check .
    .venvs/py{{ py }}/bin/ty check --python .venvs/py{{ py }} aspects tests

# Run the aspect test suite (fixture repositories in a temp dir).
test py="3.11": (venv py)
    .venvs/py{{ py }}/bin/pytest

# What CI runs: check, then test.
ci py="3.11": (check py) (test py)

# --- aspect development (meta) ------------------------------------------------
# Exercise the python-package aspect's checker against the WAMP packages (siblings
# under ../). For developing the aspect itself, not part of the aspect.
test-check:
    python3 aspects/python-package/scripts/check.py \
        ../txaio ../autobahn-python ../crossbar ../zlmdb ../cfxdb ../wamp-xbr

# Dry-run the python-package reconciler (the rollout COMPUTE step) against the WAMP
# packages - prints the proposed ChangeSet; changes nothing.
test-reconcile:
    python3 aspects/python-package/scripts/reconcile.py \
        ../txaio ../autobahn-python ../crossbar ../zlmdb ../cfxdb ../wamp-xbr

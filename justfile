# Copyright (C) typedef int GmbH
# SPDX-License-Identifier: MIT

# The recipes below follow the estate's justfile standard (autobahn-python), keeping
# only what an aspect repository needs: no package version, build, docs or publish
# recipes - this repository builds nothing; its aspect scripts are run by path.

# -----------------------------------------------------------------------------
# -- just global configuration
# -----------------------------------------------------------------------------

set unstable := true
set positional-arguments := true
set script-interpreter := ['uv', 'run', '--script']
set shell := ["bash", "-uc"]

# -----------------------------------------------------------------------------
# -- Way-A shared workflow recipes (wamp-cicd workflow.just)
# -----------------------------------------------------------------------------
# This repository is submodule-free: wamp-cicd is a plain checkout under .deps/
# (deps.toml, scripts/deps.sh), hence the optional import. The default branch is
# `main`, workflow.just's default, so WORKFLOW_MAIN is not overridden.
import? '.deps/wamp-cicd/workflow.just'

# project base directory = directory of this justfile
PROJECT_DIR := justfile_directory()

# Default recipe: show project header and list all recipes
default:
    #!/usr/bin/env bash
    set -e
    GIT_REV=$(git rev-parse --short HEAD 2>/dev/null || echo "unknown")
    ASPECTS=$(cd aspects && ls -d */ 2>/dev/null | tr -d '/' | tr '\n' ' ')
    echo ""
    echo "==============================================================================="
    echo "                          autobahn-crossbar-ai                                 "
    echo ""
    echo "     Aspects (Agent Skills) for the autobahn-crossbar fleet of repositories    "
    echo ""
    echo "   Aspects:                ${ASPECTS}"
    echo "   Git Version:            ${GIT_REV}                                         "
    echo "   Source Code:            https://github.com/crossbario/autobahn-crossbar-ai "
    echo "   Copyright:              typedef int GmbH (Germany/EU)                      "
    echo "   License:                MIT License                                        "
    echo "==============================================================================="
    echo ""
    just --list
    echo ""

# Tell uv to always copy files instead of trying to hardlink them.
# set export UV_LINK_MODE := 'copy'

# Tell uv to use project-local cache directory.
export UV_CACHE_DIR := './.uv-cache'

# Use this common single directory for all uv venvs.
# Use absolute path (based on PROJECT_DIR) to avoid issues when cd'ing in recipes
VENV_DIR := PROJECT_DIR / '.venvs'

# Define a justfile-local variable for our environments.
# PyPy publishes no Windows ARM64 interpreter, so win_arm64 is CPython-only.
ENVS := if os() + "-" + arch() == "windows-aarch64" { 'cpy314 cpy313 cpy312 cpy311' } else { 'cpy314 cpy313 cpy312 cpy311 pypy311' }

# On Windows ARM64 a bare request like `cpython-3.11` resolves to the *x86_64* build;
# qualify the request so the aarch64 interpreter is selected.
PY_PLATFORM_SUFFIX := if os() + "-" + arch() == "windows-aarch64" { '-windows-aarch64-none' } else { '' }

_get-spec short_name:
    #!/usr/bin/env bash
    set -e
    case {{short_name}} in
        cpy314)  echo "cpython-3.14{{PY_PLATFORM_SUFFIX}}";;
        cpy313)  echo "cpython-3.13{{PY_PLATFORM_SUFFIX}}";;
        cpy312)  echo "cpython-3.12{{PY_PLATFORM_SUFFIX}}";;
        cpy311)  echo "cpython-3.11{{PY_PLATFORM_SUFFIX}}";;
        pypy311) echo "pypy-3.11.15";;  # PyPy 7.3.23 = last pp73 ABI; pinned as in autobahn-python
        *)       echo "Unknown environment: {{short_name}}" >&2; exit 1;;
    esac

# Internal helper that calculates and prints the system-matching venv name.
_get-system-venv-name:
    #!/usr/bin/env bash
    set -e
    SYSTEM_VERSION=$(/usr/bin/python3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
    ENV_NAME="cpy$(echo ${SYSTEM_VERSION} | tr -d '.')"

    if ! echo "{{ ENVS }}" | grep -q -w "${ENV_NAME}"; then
        echo "Error: System Python (${SYSTEM_VERSION}) maps to '${ENV_NAME}', which is not a supported environment in this project." >&2
        exit 1
    fi
    # The only output of this recipe is the name itself.
    echo "${ENV_NAME}"

# Helper recipe to get the python executable path for a venv
_get-venv-python venv="":
    #!/usr/bin/env bash
    set -e
    VENV_NAME="{{ venv }}"
    if [ -z "${VENV_NAME}" ]; then
        VENV_NAME=$(just --quiet _get-system-venv-name)
    fi
    VENV_PATH="{{VENV_DIR}}/${VENV_NAME}"
    if [[ "$OS" == "Windows_NT" ]]; then
        echo "${VENV_PATH}/Scripts/python.exe"
    else
        echo "${VENV_PATH}/bin/python3"
    fi

# -----------------------------------------------------------------------------
# -- General/global helper recipes
# -----------------------------------------------------------------------------

# Setup bash tab completion for the current user (to activate: `source ~/.config/bash_completion`).
setup-completion:
    #!/usr/bin/env bash
    set -e

    COMPLETION_FILE="${XDG_CONFIG_HOME:-$HOME/.config}/bash_completion"
    MARKER="# --- Just completion ---"

    echo "==> Setting up bash tab completion for 'just'..."

    if [ -f "${COMPLETION_FILE}" ] && grep -q "${MARKER}" "${COMPLETION_FILE}"; then
        echo "--> 'just' completion is already configured."
        exit 0
    fi

    echo "--> Configuration not found. Adding it now..."
    mkdir -p "$(dirname "${COMPLETION_FILE}")"
    echo "" >> "${COMPLETION_FILE}"
    echo "${MARKER}" >> "${COMPLETION_FILE}"
    just --completions bash >> "${COMPLETION_FILE}"

    echo "--> Successfully added completion logic to ${COMPLETION_FILE}."
    echo ""
    echo "==> Setup complete. Please restart your shell or run the following command:"
    echo "    source \"${COMPLETION_FILE}\""

# Make `.deps/` what `deps.toml` says: this repository's dependencies as plain checkouts at pinned commits - it carries no submodules (see TOOLING-STRUCTURE.md).
deps *args:
    bash scripts/deps.sh sync {{args}}

# Internal guard: `.deps/` must match deps.toml (AI_POLICY.md and CLAUDE.md link into it).
_deps-ok:
    @bash scripts/deps.sh check >/dev/null || { echo "ERROR: .deps/ does not match deps.toml - run: just deps" >&2; exit 1; }

# Remove ALL generated files, including venvs, caches, and coverage. WARNING: This is a destructive operation.
distclean:
    #!/usr/bin/env bash
    set -e

    echo "==> Performing a deep clean (distclean)..."

    echo "--> Removing venvs, caches and coverage reports..."
    rm -rf {{UV_CACHE_DIR}} {{VENV_DIR}} .pytest_cache/ .ruff_cache/ .ty/ htmlcov/

    echo "--> Searching for and removing nested Python caches..."
    find . -type d -name "__pycache__" -exec rm -rf {} +

    echo "--> Searching for and removing compiled Python files..."
    find . -type f -name "*.pyc" -delete
    find . -type f -name "*.pyo" -delete

    echo "--> Searching for and removing coverage data..."
    rm -f .coverage
    find . -type f -name ".coverage.*" -delete

    echo "==> Distclean complete. The project is now pristine."

# -----------------------------------------------------------------------------
# -- Python virtual environments
# -----------------------------------------------------------------------------

# List all Python virtual environments
list-all:
    #!/usr/bin/env bash
    set -e
    echo
    echo "Available CPython run-times:"
    echo "============================"
    echo
    uv python list --all-platforms cpython
    echo
    echo "Available PyPy run-times:"
    echo "========================="
    echo
    uv python list --all-platforms pypy
    echo
    echo "Mapped Python run-time shortname => full version:"
    echo "================================================="
    echo
    for env in {{ENVS}}; do
        spec=$(just --quiet _get-spec "$env")
        echo "  - $env => $spec"
    done
    echo
    echo "Create a Python venv using: just create <shortname>"

# Create a single Python virtual environment (usage: `just create cpy314` or `just create`)
create venv="":
    #!/usr/bin/env bash
    set -e

    VENV_NAME="{{ venv }}"
    if [ -z "${VENV_NAME}" ]; then
        echo "==> No venv name specified. Auto-detecting from system Python..."
        VENV_NAME=$(just --quiet _get-system-venv-name)
        echo "==> Defaulting to venv: '${VENV_NAME}'"
    fi

    VENV_PATH="{{ VENV_DIR }}/${VENV_NAME}"
    VENV_PYTHON=$(just --quiet _get-venv-python "${VENV_NAME}")

    # A venv whose interpreter is gone is stale (e.g. built against a uv-managed Python
    # that has since been removed): recreate it instead of reusing it.
    if [ -d "${VENV_PATH}" ] && [ ! -x "${VENV_PYTHON}" ]; then
        echo "==> Python virtual environment '${VENV_NAME}' in ${VENV_PATH} has no working interpreter, recreating it..."
        rm -rf "${VENV_PATH}"
    fi

    if [ ! -d "${VENV_PATH}" ]; then
        PYTHON_SPEC=$(just --quiet _get-spec "${VENV_NAME}")
        echo "==> Creating Python virtual environment '${VENV_NAME}' using ${PYTHON_SPEC} in ${VENV_PATH}..."
        mkdir -p "{{ VENV_DIR }}"
        uv venv --seed --python "${PYTHON_SPEC}" "${VENV_PATH}"
        echo "==> Successfully created venv '${VENV_NAME}'."
    else
        echo "==> Python virtual environment '${VENV_NAME}' already exists in ${VENV_PATH}."
    fi

    ${VENV_PYTHON} -V
    ${VENV_PYTHON} -m pip -V

    echo "==> Activate Python virtual environment with: source ${VENV_PATH}/bin/activate"

# Meta-recipe to run `create` on all environments
create-all:
    #!/usr/bin/env bash
    for venv in {{ENVS}}; do
        just create ${venv}
    done

# Get the version of a single virtual environment's Python (usage: `just version cpy314`)
version venv="":
    #!/usr/bin/env bash
    set -e
    VENV_NAME="{{ venv }}"
    if [ -z "${VENV_NAME}" ]; then
        echo "==> No venv name specified. Auto-detecting from system Python..."
        VENV_NAME=$(just --quiet _get-system-venv-name)
        echo "==> Defaulting to venv: '${VENV_NAME}'"
    fi

    if [ -d "{{ VENV_DIR }}/${VENV_NAME}" ]; then
        echo "==> Python virtual environment '${VENV_NAME}' exists:"
        "{{VENV_DIR}}/${VENV_NAME}/bin/python" -V
    else
        echo "==>  Python virtual environment '${VENV_NAME}' does not exist."
    fi
    echo ""

# Get versions of all Python virtual environments
version-all:
    #!/usr/bin/env bash
    for venv in {{ENVS}}; do
        just version ${venv}
    done

# -----------------------------------------------------------------------------
# -- Installation: Tools (Ruff, ty, pytest)
# -----------------------------------------------------------------------------

# No package to install (`-e .[dev]`): the tools are the PEP 735 dependency group `dev`.
# Install the development tools in a single environment (usage: `just install-tools cpy314`)
install-tools venv="": (create venv)
    #!/usr/bin/env bash
    set -e
    VENV_NAME="{{ venv }}"
    if [ -z "${VENV_NAME}" ]; then
        echo "==> No venv name specified. Auto-detecting from system Python..."
        VENV_NAME=$(just --quiet _get-system-venv-name)
        echo "==> Defaulting to venv: '${VENV_NAME}'"
    fi
    VENV_PYTHON=$(just --quiet _get-venv-python "${VENV_NAME}")
    echo "==> Installing development tools in ${VENV_NAME}..."

    ${VENV_PYTHON} -V
    ${VENV_PYTHON} -m pip -V

    # dependency groups need pip >= 25.1
    ${VENV_PYTHON} -m pip install -q -U "pip>=25.1"
    ${VENV_PYTHON} -m pip install -q --group dev

# Meta-recipe to run `install-tools` on all environments
install-tools-all:
    #!/usr/bin/env bash
    set -e
    for venv in {{ENVS}}; do
        just install-tools ${venv}
    done

# -----------------------------------------------------------------------------
# -- Linting, Static Typechecking, .. the codebase
# -----------------------------------------------------------------------------

# Automatically fix all formatting and code style issues.
fix-format venv="": (_deps-ok) (install-tools venv)
    #!/usr/bin/env bash
    set -e
    VENV_NAME="{{ venv }}"
    if [ -z "${VENV_NAME}" ]; then
        echo "==> No venv name specified. Auto-detecting from system Python..."
        VENV_NAME=$(just --quiet _get-system-venv-name)
        echo "==> Defaulting to venv: '${VENV_NAME}'"
    fi
    VENV_PATH="{{ VENV_DIR }}/${VENV_NAME}"

    echo "==> Automatically formatting code with ${VENV_NAME}..."
    # 1. The FORMATTER first (line lengths, quotes, ...).
    "${VENV_PATH}/bin/ruff" format .
    # 2. The LINTER'S FIXER second (unused imports, import order, ...).
    "${VENV_PATH}/bin/ruff" check --fix .
    echo "--> Formatting complete."

# Alias for fix-format (backward compatibility)
autoformat venv="": (fix-format venv)

# Lint code using Ruff in a single environment
check-format venv="": (_deps-ok) (install-tools venv)
    #!/usr/bin/env bash
    set -e
    VENV_NAME="{{ venv }}"
    if [ -z "${VENV_NAME}" ]; then
        echo "==> No venv name specified. Auto-detecting from system Python..."
        VENV_NAME=$(just --quiet _get-system-venv-name)
        echo "==> Defaulting to venv: '${VENV_NAME}'"
    fi
    VENV_PATH="{{ VENV_DIR }}/${VENV_NAME}"
    echo "==> Linting code with ${VENV_NAME}..."
    "${VENV_PATH}/bin/ruff" check .
    "${VENV_PATH}/bin/ruff" format --check .

# Run static type checking with ty (Astral's Rust-based type checker)
check-typing venv="": (_deps-ok) (install-tools venv)
    #!/usr/bin/env bash
    set -e
    VENV_NAME="{{ venv }}"
    if [ -z "${VENV_NAME}" ]; then
        echo "==> No venv name specified. Auto-detecting from system Python..."
        VENV_NAME=$(just --quiet _get-system-venv-name)
        echo "==> Defaulting to venv: '${VENV_NAME}'"
    fi
    VENV_PATH="{{ VENV_DIR }}/${VENV_NAME}"
    echo "==> Running static type checks with ty (using ${VENV_NAME})..."
    # The aspect scripts and their tests; no ignores.
    "${VENV_PATH}/bin/ty" check --python "${VENV_PATH}/bin/python" aspects tests

# Run the tests with coverage of the aspect scripts (usage: `just check-coverage cpy314`)
check-coverage venv="": (_deps-ok) (install-tools venv)
    #!/usr/bin/env bash
    set -e
    VENV_NAME="{{ venv }}"
    if [ -z "${VENV_NAME}" ]; then
        echo "==> No venv name specified. Auto-detecting from system Python..."
        VENV_NAME=$(just --quiet _get-system-venv-name)
        echo "==> Defaulting to venv: '${VENV_NAME}'"
    fi
    VENV_PATH="{{ VENV_DIR }}/${VENV_NAME}"
    echo "==> Running tests with coverage with ${VENV_NAME}..."
    "${VENV_PATH}/bin/pytest" \
        --cov=aspects \
        --cov-report=term-missing \
        --cov-report=html:htmlcov
    echo "--> Coverage report generated in htmlcov/index.html"

# Run all checks: lint + format, types, tests with coverage (usage: `just check cpy314`)
check venv="": (check-format venv) (check-typing venv) (check-coverage venv)

# -----------------------------------------------------------------------------
# -- Unit tests
# -----------------------------------------------------------------------------

# Run the test suite (usage: `just test cpy314`)
test venv="": (_deps-ok) (install-tools venv)
    #!/usr/bin/env bash
    set -e
    VENV_NAME="{{ venv }}"
    if [ -z "${VENV_NAME}" ]; then
        echo "==> No venv name specified. Auto-detecting from system Python..."
        VENV_NAME=$(just --quiet _get-system-venv-name)
        echo "==> Defaulting to venv: '${VENV_NAME}'"
    fi
    VENV_PATH="{{ VENV_DIR }}/${VENV_NAME}"
    echo "==> Running the test suite with ${VENV_NAME}..."
    "${VENV_PATH}/bin/pytest"

# Meta-recipe to run `test` on all environments
test-all:
    #!/usr/bin/env bash
    set -e
    for venv in {{ENVS}}; do
        just test ${venv}
    done

# -----------------------------------------------------------------------------
# -- Aspect development: exercise the aspects against the fleet
# -----------------------------------------------------------------------------
# For developing an aspect, not part of it: run it against the sibling clones (../).

# Run the python-package checker against the six autobahn-crossbar packages (../)
test-check:
    python3 aspects/python-package/scripts/check.py \
        ../txaio ../autobahn-python ../crossbar ../zlmdb ../cfxdb ../wamp-xbr

# Dry-run the python-package reconciler against them: prints the ChangeSets, changes nothing
test-reconcile:
    python3 aspects/python-package/scripts/reconcile.py \
        ../txaio ../autobahn-python ../crossbar ../zlmdb ../cfxdb ../wamp-xbr

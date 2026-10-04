set shell := ["bash", "-uc"]
import? '.deps/wamp-cicd/workflow.just'

# --- aspect development (meta) ------------------------------------------------
# Exercise the python-package aspect's checker against the WAMP packages (siblings
# under ../). For developing the aspect itself, not part of the aspect.
test-check:
    python3 aspects/python-package/scripts/check.py \
        ../txaio ../autobahn-python ../crossbar ../zlmdb ../cfxdb ../wamp-xbr

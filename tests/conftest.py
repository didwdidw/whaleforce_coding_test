"""Test-session configuration.

The artifact store refuses to start on non-mounted storage in production mode (A11.5),
which is correct for the deployment and wrong for a test run: a `tmp_path` is an ordinary
directory on the same filesystem as `/`. The requirement is switched off here explicitly —
by the same environment variable an operator would use — and the production behaviour is
asserted directly in `test_persistence_and_vacuity.py` rather than being assumed.
"""

import os
import tempfile

os.environ.setdefault("REQUIRE_PERSISTENT_STORE", "false")

# `app.server` builds its store at import time, so importing it — which the frontend claim
# tests must do — needs a writable data directory before that happens. The production
# default is `/data/task1`, which is correct there and unwritable here.
os.environ.setdefault("DATA_DIR", tempfile.mkdtemp(prefix="wf-test-data-"))

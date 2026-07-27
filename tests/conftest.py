"""Test-session configuration.

The artifact store refuses to start on non-mounted storage in production mode (A11.5),
which is correct for the deployment and wrong for a test run: a `tmp_path` is an ordinary
directory on the same filesystem as `/`. The requirement is switched off here explicitly —
by the same environment variable an operator would use — and the production behaviour is
asserted directly in `test_persistence_and_vacuity.py` rather than being assumed.
"""

import os

os.environ.setdefault("REQUIRE_PERSISTENT_STORE", "false")

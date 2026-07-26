#!/usr/bin/env bash
# One image, two services. Zeabur binds a domain per service, so the app and the fixture
# are deployed from the same repo with different APP_ROLE values and each gets its own
# *.zeabur.app hostname. That is what lets the fixture be reached over a public name with
# no allow-list hole in the egress guard (S-2.8).
set -euo pipefail

ROLE="${APP_ROLE:-app}"
PORT="${PORT:-8080}"

case "$ROLE" in
  app)
    # Refuses to start if the SSRF guard is disabled outside a dev environment.
    exec python -m uvicorn app.server:app --host 0.0.0.0 --port "$PORT" \
         --log-level "${LOG_LEVEL:-info}" --timeout-keep-alive 65
    ;;
  fixture)
    exec python -m uvicorn fixture.server:app --host 0.0.0.0 --port "$PORT" \
         --log-level "${LOG_LEVEL:-info}"
    ;;
  *)
    echo "Unknown APP_ROLE '$ROLE'. Expected 'app' or 'fixture'." >&2
    exit 64
    ;;
esac

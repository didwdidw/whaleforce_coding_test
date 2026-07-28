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
  scored)
    # Runs the eval splits with the billing credential against a loopback-only server, so
    # nothing scored ever travels the public path and the paid key never lands on the
    # container that serves anonymous traffic (A12.3, A18.10). Publishing a domain on this
    # service would break the property it exists to hold.
    exec python -m eval.scored_workload
    ;;
  *)
    echo "Unknown APP_ROLE '$ROLE'. Expected 'app', 'fixture' or 'scored'." >&2
    exit 64
    ;;
esac

"""Run and artifact persistence.

SQLite for run records and traces; the filesystem for artifact bytes. Locator memory
(§8) will live here too and is why this is a database rather than a process dictionary —
it must survive restarts, and the browser is recycled on a schedule.

Artifact expiry is a **recorded state, not a deletion of the reference** (A9.7.2). An
evidence bundle whose artifact has aged out still resolves to a row saying so, with its
hash and length intact, because a reported result pointing at a missing file is worse than
one pointing at an expired one.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from app.config import settings
from app.models import (
    BudgetUse, DiagnosedCause, FailureClass, Run, RunState, StepKind, StrategyFamily,
    TerminalStatus, TraceEntry, Tier,
)

log = logging.getLogger(__name__)


def _utc_day() -> str:
    return time.strftime("%Y-%m-%d", time.gmtime())

SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    id                 TEXT PRIMARY KEY,
    task               TEXT NOT NULL,
    tier               TEXT NOT NULL,
    state              TEXT NOT NULL,
    session_id         TEXT,
    created_at         REAL NOT NULL,
    started_at         REAL,
    finished_at        REAL,
    terminal_status    TEXT,
    failure_class      TEXT,
    explanation        TEXT,
    postcondition      TEXT,
    postcondition_hash TEXT,
    credential_tier    TEXT,
    browser_generation INTEGER,
    pre_executed       INTEGER NOT NULL DEFAULT 0,
    budget             TEXT,
    claims             TEXT,
    suspicions         TEXT,
    execution_path     TEXT
);
CREATE INDEX IF NOT EXISTS runs_created ON runs (created_at DESC);
CREATE INDEX IF NOT EXISTS runs_session ON runs (session_id);

CREATE TABLE IF NOT EXISTS trace (
    run_id          TEXT NOT NULL,
    seq             INTEGER NOT NULL,
    kind            TEXT NOT NULL,
    summary         TEXT NOT NULL,
    started_at      REAL NOT NULL,
    finished_at     REAL,
    ok              INTEGER NOT NULL,
    detail          TEXT,
    diagnosed_cause TEXT,
    family_from     TEXT,
    family_to       TEXT,
    artifact_id     TEXT,
    PRIMARY KEY (run_id, seq)
);

CREATE TABLE IF NOT EXISTS artifacts (
    id           TEXT PRIMARY KEY,
    run_id       TEXT NOT NULL,
    kind         TEXT NOT NULL,
    source_url   TEXT,
    retrieved_at REAL NOT NULL,
    media_type   TEXT,
    length       INTEGER NOT NULL,
    sha256       TEXT NOT NULL,
    path         TEXT,
    -- 'stored' or 'expired'. Expiry keeps the row, the hash and the length; only the
    -- bytes go. A dangling reference is never produced.
    state        TEXT NOT NULL DEFAULT 'stored',
    expired_at   REAL,
    -- Pinned artifacts are never evicted, by age or by disk pressure (A11.3). The
    -- homepage's demonstrations are the whole of the pinned set.
    pinned       INTEGER NOT NULL DEFAULT 0
);

-- Every eviction, so evidence disappearing is a recorded operational event rather than
-- something noticed later by a broken link (A11.6).
CREATE TABLE IF NOT EXISTS retention_events (
    at        REAL NOT NULL,
    reason    TEXT NOT NULL,
    artifacts INTEGER NOT NULL,
    bytes     INTEGER NOT NULL,
    detail    TEXT
);
CREATE INDEX IF NOT EXISTS artifacts_run ON artifacts (run_id);
CREATE INDEX IF NOT EXISTS artifacts_state ON artifacts (state, retrieved_at);

-- Cumulative provider spend, per UTC day and per credential tier. A8.10's USD 5 ceiling
-- existed only as a number someone was holding in their head; this is what lets the code
-- refuse rather than remember.
CREATE TABLE IF NOT EXISTS provider_spend (
    day   TEXT NOT NULL,
    tier  TEXT NOT NULL,
    usd   REAL NOT NULL DEFAULT 0,
    calls INTEGER NOT NULL DEFAULT 0,
    input_tokens  INTEGER NOT NULL DEFAULT 0,
    output_tokens INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (day, tier)
);

-- Which terminal statuses and failure classes have ever actually been produced. An empty
-- failure_class is stored as '' rather than NULL so the primary key stays meaningful.
CREATE TABLE IF NOT EXISTS status_coverage (
    terminal_status TEXT NOT NULL,
    failure_class   TEXT NOT NULL DEFAULT '',
    first_run_id    TEXT,
    first_seen_at   REAL NOT NULL,
    origin          TEXT NOT NULL DEFAULT 'run',
    task            TEXT,
    n               INTEGER NOT NULL DEFAULT 1,
    PRIMARY KEY (terminal_status, failure_class)
);
"""


def _unavailable(path: Path, error: str) -> str:
    return (
        f"REFUSING TO START: the artifact store at {path} is not usable ({error}).\n"
        f"Evidence bundles are the product's central claim, so writing them somewhere that "
        f"disappears on the next deploy is not an acceptable fallback — it works, it looks "
        f"fine, and every stored artifact is gone the next time the service restarts.\n"
        f"In production: attach the persistent volume and mount it at the parent of this "
        f"path. Locally: set DATA_DIR to a writable directory.")


class StoreUnavailable(RuntimeError):
    """The artifact store is not mounted or not writable.

    In production this is a startup failure (A10.8, A11.5). Falling back to ephemeral
    storage would work, look fine, and destroy every evidence bundle on the next deploy —
    which is exactly the condition the volume exists to fix.
    """


@dataclass
class ArtifactRef:
    id: str
    run_id: str
    kind: str
    source_url: str | None
    retrieved_at: float
    media_type: str | None
    length: int
    sha256: str
    state: str
    expired_at: float | None = None
    pinned: bool = False

    @property
    def retrieved_on(self) -> str:
        return time.strftime("%Y-%m-%d", time.gmtime(self.retrieved_at))

    @property
    def expired_on(self) -> str | None:
        """The date expiry happened, so the UI can say "expired on 2026-08-10" rather than
        showing an empty panel (A11.4)."""
        if self.expired_at is None:
            return None
        return time.strftime("%Y-%m-%d", time.gmtime(self.expired_at))

    def to_dict(self) -> dict[str, Any]:
        return {
            "artifact_id": self.id,
            "kind": self.kind,
            "source_url": self.source_url,
            "retrieved_at": self.retrieved_at,
            "retrieved_on": self.retrieved_on,
            "media_type": self.media_type,
            "length": self.length,
            "sha256": self.sha256,
            "state": self.state,
            "expired_at": self.expired_at,
            "expired_on": self.expired_on,
            "pinned": self.pinned,
            "available": self.state == "stored",
        }


class Store:
    def __init__(self, db_path: Path | None = None, artifact_dir: Path | None = None) -> None:
        self.db_path = db_path if db_path is not None else settings.db_path
        self.artifact_dir = (artifact_dir if artifact_dir is not None
                             else settings.artifact_dir)
        try:
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
            self.artifact_dir.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise StoreUnavailable(_unavailable(self.artifact_dir, str(exc))) from exc
        probe = self.probe()
        if not probe["writable"]:
            raise StoreUnavailable(_unavailable(self.artifact_dir, probe["error"]))
        if settings.require_persistent_store and not probe["mounted"]:
            raise StoreUnavailable(_unavailable(
                self.artifact_dir,
                "it is on the container's own filesystem, not a mounted volume — the "
                "directory exists and is writable, which is exactly why this would "
                "otherwise go unnoticed until a deploy deleted every artifact"))
        self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(SCHEMA)
        self._migrate()
        self._conn.commit()

    def _migrate(self) -> None:
        """Add columns a previously-created database does not have.

        `CREATE TABLE IF NOT EXISTS` does nothing to an existing table, which was harmless
        while storage was ephemeral and stops being harmless the moment a volume makes the
        database outlive the code that wrote it.
        """
        existing = {row["name"] for row in
                    self._conn.execute("PRAGMA table_info(artifacts)")}
        if "pinned" not in existing:
            self._conn.execute(
                "ALTER TABLE artifacts ADD COLUMN pinned INTEGER NOT NULL DEFAULT 0")
            self._conn.commit()
        run_columns = {row["name"] for row in self._conn.execute("PRAGMA table_info(runs)")}
        if "suspicions" not in run_columns:
            self._conn.execute("ALTER TABLE runs ADD COLUMN suspicions TEXT")
            self._conn.commit()
        if "execution_path" not in run_columns:
            self._conn.execute("ALTER TABLE runs ADD COLUMN execution_path TEXT")
            self._conn.commit()

    def probe(self) -> dict[str, Any]:
        """Confirm the store is really writable by writing to it (A11.5).

        A path-existence check passes on an unmounted directory, a read-only mount and a
        full disk alike — all three of which are exactly the states this needs to catch.
        """
        marker = self.artifact_dir / ".write-probe"
        payload = f"{time.time():.6f}".encode()
        result: dict[str, Any] = {"path": str(self.artifact_dir),
                                  "mounted": self._on_its_own_device(),
                                  "checked_at": time.time()}
        try:
            marker.write_bytes(payload)
            ok = marker.read_bytes() == payload
            marker.unlink(missing_ok=True)
            return {**result, "writable": ok,
                    "error": None if ok else "readback did not match what was written"}
        except OSError as exc:
            return {**result, "writable": False, "error": f"{type(exc).__name__}: {exc}"}

    def _on_its_own_device(self) -> bool:
        """True when the data directory sits on a different filesystem from `/`.

        A mounted volume has its own device id; a directory the image happened to create
        does not. This is the difference between persistent storage and storage that looks
        persistent right up until the next deploy.
        """
        try:
            return os.stat(self.artifact_dir).st_dev != os.stat("/").st_dev
        except OSError:
            return False

    def close(self) -> None:
        self._conn.close()

    # ---- runs ------------------------------------------------------------------

    def save_run(self, run: Run) -> None:
        self._conn.execute(
            """INSERT INTO runs (id, task, tier, state, session_id, created_at, started_at,
                                 finished_at, terminal_status, failure_class, explanation,
                                 postcondition, postcondition_hash, credential_tier,
                                 browser_generation, pre_executed, budget, claims,
                                 suspicions, execution_path)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
               ON CONFLICT(id) DO UPDATE SET
                 state=excluded.state, started_at=excluded.started_at,
                 finished_at=excluded.finished_at, terminal_status=excluded.terminal_status,
                 failure_class=excluded.failure_class, explanation=excluded.explanation,
                 postcondition=excluded.postcondition,
                 postcondition_hash=excluded.postcondition_hash,
                 credential_tier=excluded.credential_tier,
                 browser_generation=excluded.browser_generation,
                 budget=excluded.budget, claims=excluded.claims,
                 suspicions=excluded.suspicions,
                 execution_path=excluded.execution_path""",
            (run.id, run.task, run.tier.value, run.state.value, run.session_id,
             run.created_at, run.started_at, run.finished_at,
             run.terminal_status.value if run.terminal_status else None,
             run.failure_class.value if run.failure_class else None,
             run.explanation,
             json.dumps(run.postcondition) if run.postcondition else None,
             run.postcondition_hash, run.credential_tier, run.browser_generation,
             int(run.pre_executed), json.dumps(run.budget.to_dict()),
             json.dumps(run.claims), json.dumps(run.suspicions),
             run.execution_path),
        )
        self._conn.commit()

    def save_trace_entry(self, run_id: str, entry: TraceEntry) -> None:
        self._conn.execute(
            """INSERT INTO trace (run_id, seq, kind, summary, started_at, finished_at, ok,
                                  detail, diagnosed_cause, family_from, family_to, artifact_id)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
               ON CONFLICT(run_id, seq) DO UPDATE SET
                 finished_at=excluded.finished_at, ok=excluded.ok, detail=excluded.detail,
                 summary=excluded.summary, artifact_id=excluded.artifact_id""",
            (run_id, entry.seq, entry.kind.value, entry.summary, entry.started_at,
             entry.finished_at, int(entry.ok), json.dumps(entry.detail),
             entry.diagnosed_cause.value if entry.diagnosed_cause else None,
             entry.family_from.value if entry.family_from else None,
             entry.family_to.value if entry.family_to else None, entry.artifact_id),
        )
        self._conn.commit()

    def load_run(self, run_id: str) -> Run | None:
        row = self._conn.execute("SELECT * FROM runs WHERE id = ?", (run_id,)).fetchone()
        if row is None:
            return None
        run = self._row_to_run(row)
        for t in self._conn.execute(
                "SELECT * FROM trace WHERE run_id = ? ORDER BY seq", (run_id,)):
            run.trace.append(TraceEntry(
                seq=t["seq"], kind=StepKind(t["kind"]), summary=t["summary"],
                started_at=t["started_at"], finished_at=t["finished_at"], ok=bool(t["ok"]),
                detail=json.loads(t["detail"]) if t["detail"] else {},
                diagnosed_cause=DiagnosedCause(t["diagnosed_cause"]) if t["diagnosed_cause"] else None,
                family_from=StrategyFamily(t["family_from"]) if t["family_from"] else None,
                family_to=StrategyFamily(t["family_to"]) if t["family_to"] else None,
                artifact_id=t["artifact_id"],
            ))
        return run

    def recent_runs(self, limit: int = 25, *, pre_executed: bool | None = None) -> list[Run]:
        sql = "SELECT * FROM runs"
        params: list[Any] = []
        if pre_executed is not None:
            sql += " WHERE pre_executed = ?"
            params.append(int(pre_executed))
        sql += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)
        return [self._row_to_run(r) for r in self._conn.execute(sql, params)]

    def session_run_count(self, session_id: str) -> int:
        row = self._conn.execute(
            "SELECT COUNT(*) AS n FROM runs WHERE session_id = ? AND pre_executed = 0",
            (session_id,)).fetchone()
        return int(row["n"])

    @staticmethod
    def _row_to_run(row: sqlite3.Row) -> Run:
        budget = BudgetUse()
        if row["budget"]:
            data = json.loads(row["budget"])
            budget.steps = data.get("steps", 0)
            budget.llm_calls_exploration = data.get("llm_calls_exploration", 0)
            budget.llm_calls_recovery = data.get("llm_calls_recovery", 0)
            budget.input_tokens = data.get("input_tokens", 0)
            budget.output_tokens = data.get("output_tokens", 0)
            budget.usd = data.get("usd", 0.0)
            budget.started_at = data.get("started_at") or row["started_at"] or budget.started_at
            budget.ended_at = data.get("ended_at")
        return Run(
            id=row["id"], task=row["task"], tier=Tier(row["tier"]),
            state=RunState(row["state"]), session_id=row["session_id"] or "",
            created_at=row["created_at"], started_at=row["started_at"],
            finished_at=row["finished_at"],
            terminal_status=TerminalStatus(row["terminal_status"]) if row["terminal_status"] else None,
            failure_class=FailureClass(row["failure_class"]) if row["failure_class"] else None,
            explanation=row["explanation"] or "",
            postcondition=json.loads(row["postcondition"]) if row["postcondition"] else None,
            postcondition_hash=row["postcondition_hash"],
            credential_tier=row["credential_tier"],
            browser_generation=row["browser_generation"],
            pre_executed=bool(row["pre_executed"]),
            budget=budget,
            claims=json.loads(row["claims"]) if row["claims"] else [],
            suspicions=json.loads(row["suspicions"]) if row["suspicions"] else [],
            execution_path=row["execution_path"],
        )

    # ---- status coverage -------------------------------------------------------

    def record_status_coverage(self, terminal_status: str, failure_class: str,
                               run_id: str, task: str, origin: str) -> None:
        """First observation wins; later ones only bump the count. The point of the row is
        *when this first became reachable*, which a later overwrite would erase."""
        self._conn.execute(
            """INSERT INTO status_coverage (terminal_status, failure_class, first_run_id,
                                            first_seen_at, origin, task, n)
               VALUES (?,?,?,?,?,?,1)
               ON CONFLICT(terminal_status, failure_class) DO UPDATE SET n = n + 1""",
            (terminal_status, failure_class or "", run_id, time.time(), origin, task[:200]))
        self._conn.commit()

    def status_coverage(self) -> list[dict[str, Any]]:
        return [dict(r) for r in self._conn.execute(
            "SELECT * FROM status_coverage ORDER BY first_seen_at")]

    # ---- provider spend ---------------------------------------------------------

    def record_spend(self, tier: str, usd: float, input_tokens: int,
                     output_tokens: int) -> None:
        self._conn.execute(
            """INSERT INTO provider_spend (day, tier, usd, calls, input_tokens, output_tokens)
               VALUES (?,?,?,1,?,?)
               ON CONFLICT(day, tier) DO UPDATE SET
                 usd = usd + excluded.usd, calls = calls + 1,
                 input_tokens = input_tokens + excluded.input_tokens,
                 output_tokens = output_tokens + excluded.output_tokens""",
            (_utc_day(), tier, usd, input_tokens, output_tokens))
        self._conn.commit()

    def spend(self, *, day: str | None = None) -> dict[str, Any]:
        """Today's spend and the running total. Both matter: the daily figure is the
        operational guard, the cumulative one is what A8.10's ceiling is written against."""
        day = day or _utc_day()
        today = self._conn.execute(
            "SELECT COALESCE(SUM(usd),0) u, COALESCE(SUM(calls),0) c FROM provider_spend "
            "WHERE day = ?", (day,)).fetchone()
        total = self._conn.execute(
            "SELECT COALESCE(SUM(usd),0) u, COALESCE(SUM(calls),0) c FROM provider_spend"
        ).fetchone()
        by_tier = {r["tier"]: round(r["usd"], 6) for r in self._conn.execute(
            "SELECT tier, SUM(usd) usd FROM provider_spend GROUP BY tier")}
        return {
            "day": day,
            "today_usd": round(today["u"], 6),
            "today_calls": int(today["c"]),
            "cumulative_usd": round(total["u"], 6),
            "cumulative_calls": int(total["c"]),
            "by_tier_usd": by_tier,
        }

    # ---- artifacts -------------------------------------------------------------

    def put_artifact(self, run_id: str, kind: str, data: bytes, *,
                     source_url: str | None = None, media_type: str | None = None,
                     artifact_id: str | None = None, pinned: bool = False) -> ArtifactRef:
        from app.models import new_id
        aid = artifact_id or new_id("art")
        digest = hashlib.sha256(data).hexdigest()
        path = self.artifact_dir / f"{aid}.bin"
        try:
            path.write_bytes(data)
        except OSError as exc:
            raise StoreUnavailable(
                f"Could not write artifact {aid} to {path}: {exc}") from exc
        ref = ArtifactRef(id=aid, run_id=run_id, kind=kind, source_url=source_url,
                          retrieved_at=time.time(), media_type=media_type,
                          length=len(data), sha256=digest, state="stored", pinned=pinned)
        self._conn.execute(
            """INSERT INTO artifacts (id, run_id, kind, source_url, retrieved_at,
                                      media_type, length, sha256, path, state, pinned)
               VALUES (?,?,?,?,?,?,?,?,?,'stored',?)""",
            (aid, run_id, kind, source_url, ref.retrieved_at, media_type, ref.length,
             digest, str(path), int(pinned)))
        self._conn.commit()
        return ref

    def get_artifact_ref(self, artifact_id: str) -> ArtifactRef | None:
        row = self._conn.execute("SELECT * FROM artifacts WHERE id = ?",
                                 (artifact_id,)).fetchone()
        if row is None:
            return None
        return ArtifactRef(
            id=row["id"], run_id=row["run_id"], kind=row["kind"],
            source_url=row["source_url"], retrieved_at=row["retrieved_at"],
            media_type=row["media_type"], length=row["length"], sha256=row["sha256"],
            state=row["state"], expired_at=row["expired_at"],
            pinned=bool(row["pinned"]))

    def read_artifact(self, artifact_id: str) -> bytes | None:
        """Bytes if still stored, None if expired. Verification re-resolves anchors in the
        full stored artifact (A7.4), so an expired one must fail loudly, not silently.

        The path comes out of the database, and this store hands its contents to anyone
        over HTTP, so it is checked against the store directory before it is read. Without
        that, one bad row is the difference between serving evidence and serving whatever
        the row points at.
        """
        row = self._conn.execute(
            "SELECT path, state FROM artifacts WHERE id = ?", (artifact_id,)).fetchone()
        if row is None or row["state"] != "stored" or not row["path"]:
            return None
        path = Path(row["path"])
        if not self.contains(path):
            log.error("artifact %s points outside the store (%s); refusing to read it",
                      artifact_id, path)
            return None
        return path.read_bytes() if path.exists() else None

    def contains(self, path: Path) -> bool:
        """Whether a path is inside the artifact store. Secrets live outside it by design
        (the key directory is not under the data directory), and this is what keeps the
        design from resting on that fact alone."""
        try:
            resolved = path.resolve()
            root = self.artifact_dir.resolve()
        except OSError:
            return False
        return resolved == root or root in resolved.parents

    def artifacts_for_run(self, run_id: str) -> list[ArtifactRef]:
        return [self.get_artifact_ref(r["id"]) for r in self._conn.execute(
            "SELECT id FROM artifacts WHERE run_id = ? ORDER BY retrieved_at", (run_id,))]

    def enforce_retention(self, *, retention_days: int | None = None,
                          max_mib: int | None = None) -> dict[str, Any]:
        """Bound storage growth by expiring bytes, never rows (A9.7.2, A11.6).

        Age first, then size, oldest-first, and **never a pinned artifact**: the homepage's
        demonstrations must still resolve for a grader arriving two weeks after deployment
        (A11.3). Every eviction is recorded — evidence disappearing quietly is the thing
        this is meant to prevent, so a silent sweep would defeat its own purpose.
        """
        # `or` here would turn an explicit 0 — "expire everything now" — into the default.
        retention_days = (settings.artifact_retention_days if retention_days is None
                          else retention_days)
        max_mib = settings.artifact_store_max_mib if max_mib is None else max_mib
        ceiling = max_mib * 1024 * 1024

        cutoff = time.time() - retention_days * 86_400
        aged = self._conn.execute(
            "SELECT id, length FROM artifacts "
            "WHERE state='stored' AND pinned=0 AND retrieved_at < ?", (cutoff,)).fetchall()
        expired_by_age, bytes_by_age = self._expire(aged)
        if expired_by_age:
            self._record_retention("age", expired_by_age, bytes_by_age,
                                   {"retention_days": retention_days})

        total = self._stored_bytes()
        expired_by_size, bytes_by_size = 0, 0
        if total > ceiling:
            for row in self._conn.execute(
                    "SELECT id, length FROM artifacts WHERE state='stored' AND pinned=0 "
                    "ORDER BY retrieved_at ASC").fetchall():
                if total <= ceiling:
                    break
                n, freed = self._expire([row])
                total -= row["length"]
                expired_by_size += n
                bytes_by_size += freed
        if expired_by_size:
            self._record_retention("size", expired_by_size, bytes_by_size,
                                   {"max_mib": max_mib})

        stored = self._stored_bytes()
        fraction = stored / ceiling if ceiling else 0.0
        warn_at = settings.artifact_store_warn_fraction
        if fraction >= warn_at:
            # Visible before evidence starts disappearing, not after (A11.6).
            log.warning("artifact store at %.0f%% of its %d MiB ceiling (%d MiB stored); "
                        "evidence will begin to be evicted at 100%%",
                        fraction * 100, max_mib, stored // (1024 * 1024))
        if total > ceiling:
            log.error("artifact store still over its ceiling after a sweep: %d MiB of "
                      "%d MiB, and the remainder is pinned", total // (1024 * 1024), max_mib)
        return {
            "expired_by_age": expired_by_age,
            "expired_by_size": expired_by_size,
            "bytes_freed": bytes_by_age + bytes_by_size,
            "stored_bytes": stored,
            "retention_days": retention_days,
            "max_mib": max_mib,
            "fraction_of_ceiling": round(fraction, 3),
            "over_ceiling": total > ceiling,
            "warn": fraction >= warn_at,
        }

    def _record_retention(self, reason: str, artifacts: int, freed: int,
                          detail: dict[str, Any]) -> None:
        self._conn.execute(
            "INSERT INTO retention_events (at, reason, artifacts, bytes, detail) "
            "VALUES (?,?,?,?,?)",
            (time.time(), reason, artifacts, freed, json.dumps(detail)))
        self._conn.commit()
        log.info("retention: expired %d artifacts (%d bytes) by %s", artifacts, freed, reason)

    def retention_events(self, limit: int = 10) -> list[dict[str, Any]]:
        return [dict(r) for r in self._conn.execute(
            "SELECT * FROM retention_events ORDER BY at DESC LIMIT ?", (limit,))]

    def _stored_bytes(self) -> int:
        row = self._conn.execute(
            "SELECT COALESCE(SUM(length), 0) AS n FROM artifacts WHERE state='stored'"
        ).fetchone()
        return int(row["n"])

    def _expire(self, rows: Iterable[sqlite3.Row]) -> tuple[int, int]:
        """Reclaim bytes, keep the row. Returns (count, bytes freed)."""
        n, freed = 0, 0
        for row in rows:
            ref = self._conn.execute(
                "SELECT path, length, pinned FROM artifacts WHERE id = ?",
                (row["id"],)).fetchone()
            if ref and ref["pinned"]:
                continue          # belt and braces: pinned never expires (A11.3)
            if ref and ref["path"]:
                path = Path(ref["path"])
                # Retention deletes bytes, so it must not be able to delete anything it
                # does not own. The path comes from the database; a row pointing outside
                # the store loses its bytes-column and keeps its file.
                if self.contains(path):
                    path.unlink(missing_ok=True)
                    freed += ref["length"]
                else:
                    # The row is disowned, but nothing was reclaimed — reporting bytes we
                    # did not free would be a small lie in exactly the field an operator
                    # uses to decide whether retention is working.
                    log.error("refusing to expire %s: its path %s is outside the store",
                              row["id"], path)
            self._conn.execute(
                "UPDATE artifacts SET state='expired', expired_at=?, path=NULL WHERE id=?",
                (time.time(), row["id"]))
            n += 1
        if n:
            self._conn.commit()
        return n, freed

    def storage_status(self) -> dict[str, Any]:
        counts = {row["k"]: row["n"] for row in self._conn.execute(
            "SELECT state AS k, COUNT(*) AS n FROM artifacts GROUP BY state")}
        pinned = self._conn.execute(
            "SELECT COUNT(*) AS n FROM artifacts WHERE pinned=1").fetchone()["n"]
        stored_bytes = self._stored_bytes()
        ceiling = settings.artifact_store_max_mib * 1024 * 1024
        fraction = round(stored_bytes / ceiling, 3) if ceiling else 0.0
        probe = self.probe()
        return {
            "artifacts_stored": counts.get("stored", 0),
            "artifacts_expired": counts.get("expired", 0),
            "artifacts_pinned": pinned,
            "stored_mib": round(stored_bytes / 1024 / 1024, 1),
            "max_mib": settings.artifact_store_max_mib,
            "fraction_of_ceiling": fraction,
            "warn_fraction": settings.artifact_store_warn_fraction,
            "approaching_ceiling": fraction >= settings.artifact_store_warn_fraction,
            "retention_days": settings.artifact_retention_days,
            "data_dir": str(self.artifact_dir),
            "writable": probe["writable"],
            "on_mounted_volume": probe["mounted"],
            "mount_required": settings.require_persistent_store,
            # Persistent means the evidence outlives a deploy. In development the store is
            # an ordinary directory and this is honestly false rather than assumed true.
            "persistent": probe["writable"] and probe["mounted"],
            "write_probe": probe,
            "recent_evictions": self.retention_events(5),
            "note": ("Expired artifacts keep their row, hash, length and dates; only bytes "
                     "are removed. Pinned artifacts (the homepage demonstrations) are never "
                     "evicted."),
        }

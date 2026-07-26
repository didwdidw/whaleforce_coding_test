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
    claims             TEXT
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
    expired_at   REAL
);
CREATE INDEX IF NOT EXISTS artifacts_run ON artifacts (run_id);
CREATE INDEX IF NOT EXISTS artifacts_state ON artifacts (state, retrieved_at);

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

    def to_dict(self) -> dict[str, Any]:
        return {
            "artifact_id": self.id,
            "kind": self.kind,
            "source_url": self.source_url,
            "retrieved_at": self.retrieved_at,
            "media_type": self.media_type,
            "length": self.length,
            "sha256": self.sha256,
            "state": self.state,
            "expired_at": self.expired_at,
            "available": self.state == "stored",
        }


class Store:
    def __init__(self, db_path: Path | None = None, artifact_dir: Path | None = None) -> None:
        self.db_path = db_path or settings.db_path
        self.artifact_dir = artifact_dir or settings.artifact_dir
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.artifact_dir.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(SCHEMA)
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()

    # ---- runs ------------------------------------------------------------------

    def save_run(self, run: Run) -> None:
        self._conn.execute(
            """INSERT INTO runs (id, task, tier, state, session_id, created_at, started_at,
                                 finished_at, terminal_status, failure_class, explanation,
                                 postcondition, postcondition_hash, credential_tier,
                                 browser_generation, pre_executed, budget, claims)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
               ON CONFLICT(id) DO UPDATE SET
                 state=excluded.state, started_at=excluded.started_at,
                 finished_at=excluded.finished_at, terminal_status=excluded.terminal_status,
                 failure_class=excluded.failure_class, explanation=excluded.explanation,
                 postcondition=excluded.postcondition,
                 postcondition_hash=excluded.postcondition_hash,
                 credential_tier=excluded.credential_tier,
                 browser_generation=excluded.browser_generation,
                 budget=excluded.budget, claims=excluded.claims""",
            (run.id, run.task, run.tier.value, run.state.value, run.session_id,
             run.created_at, run.started_at, run.finished_at,
             run.terminal_status.value if run.terminal_status else None,
             run.failure_class.value if run.failure_class else None,
             run.explanation,
             json.dumps(run.postcondition) if run.postcondition else None,
             run.postcondition_hash, run.credential_tier, run.browser_generation,
             int(run.pre_executed), json.dumps(run.budget.to_dict()),
             json.dumps(run.claims)),
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

    # ---- artifacts -------------------------------------------------------------

    def put_artifact(self, run_id: str, kind: str, data: bytes, *,
                     source_url: str | None = None, media_type: str | None = None,
                     artifact_id: str | None = None) -> ArtifactRef:
        from app.models import new_id
        aid = artifact_id or new_id("art")
        digest = hashlib.sha256(data).hexdigest()
        path = self.artifact_dir / f"{aid}.bin"
        path.write_bytes(data)
        ref = ArtifactRef(id=aid, run_id=run_id, kind=kind, source_url=source_url,
                          retrieved_at=time.time(), media_type=media_type,
                          length=len(data), sha256=digest, state="stored")
        self._conn.execute(
            """INSERT INTO artifacts (id, run_id, kind, source_url, retrieved_at,
                                      media_type, length, sha256, path, state)
               VALUES (?,?,?,?,?,?,?,?,?,'stored')""",
            (aid, run_id, kind, source_url, ref.retrieved_at, media_type, ref.length,
             digest, str(path)))
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
            state=row["state"], expired_at=row["expired_at"])

    def read_artifact(self, artifact_id: str) -> bytes | None:
        """Bytes if still stored, None if expired. Verification re-resolves anchors in the
        full stored artifact (A7.4), so an expired one must fail loudly, not silently."""
        row = self._conn.execute(
            "SELECT path, state FROM artifacts WHERE id = ?", (artifact_id,)).fetchone()
        if row is None or row["state"] != "stored":
            return None
        p = Path(row["path"])
        return p.read_bytes() if p.exists() else None

    def artifacts_for_run(self, run_id: str) -> list[ArtifactRef]:
        return [self.get_artifact_ref(r["id"]) for r in self._conn.execute(
            "SELECT id FROM artifacts WHERE run_id = ? ORDER BY retrieved_at", (run_id,))]

    def enforce_retention(self, *, retention_days: int | None = None,
                          max_mib: int | None = None) -> dict[str, Any]:
        """Bound storage growth (A9.7.2) by expiring bytes, never rows.

        Age first, then size — oldest first — until the store is under its ceiling.
        """
        # `or` here would turn an explicit 0 — "expire everything now" — into the default.
        retention_days = (settings.artifact_retention_days if retention_days is None
                          else retention_days)
        max_mib = settings.artifact_store_max_mib if max_mib is None else max_mib
        cutoff = time.time() - retention_days * 86_400
        expired_by_age = self._expire(
            self._conn.execute(
                "SELECT id FROM artifacts WHERE state='stored' AND retrieved_at < ?",
                (cutoff,)).fetchall())

        total = self._stored_bytes()
        expired_by_size = 0
        if total > max_mib * 1024 * 1024:
            for row in self._conn.execute(
                    "SELECT id, length FROM artifacts WHERE state='stored' "
                    "ORDER BY retrieved_at ASC"):
                if total <= max_mib * 1024 * 1024:
                    break
                self._expire([row])
                total -= row["length"]
                expired_by_size += 1
        return {
            "expired_by_age": expired_by_age,
            "expired_by_size": expired_by_size,
            "stored_bytes": self._stored_bytes(),
            "retention_days": retention_days,
            "max_mib": max_mib,
        }

    def _stored_bytes(self) -> int:
        row = self._conn.execute(
            "SELECT COALESCE(SUM(length), 0) AS n FROM artifacts WHERE state='stored'"
        ).fetchone()
        return int(row["n"])

    def _expire(self, rows: Iterable[sqlite3.Row]) -> int:
        n = 0
        for row in rows:
            ref = self._conn.execute("SELECT path FROM artifacts WHERE id = ?",
                                     (row["id"],)).fetchone()
            if ref and ref["path"]:
                Path(ref["path"]).unlink(missing_ok=True)
            self._conn.execute(
                "UPDATE artifacts SET state='expired', expired_at=?, path=NULL WHERE id=?",
                (time.time(), row["id"]))
            n += 1
        if n:
            self._conn.commit()
        return n

    def storage_status(self) -> dict[str, Any]:
        stored = self._conn.execute(
            "SELECT COUNT(*) AS n FROM artifacts WHERE state='stored'").fetchone()["n"]
        expired = self._conn.execute(
            "SELECT COUNT(*) AS n FROM artifacts WHERE state='expired'").fetchone()["n"]
        return {
            "artifacts_stored": stored,
            "artifacts_expired": expired,
            "stored_mib": round(self._stored_bytes() / 1024 / 1024, 1),
            "max_mib": settings.artifact_store_max_mib,
            "retention_days": settings.artifact_retention_days,
            "note": "Expired artifacts keep their row, hash and length; only bytes are removed.",
        }

"""A scored round's evidence leaves the volume with the round (A22.7, A22.8).

The workload that runs scored splits has a volume nothing else can read, so without this
the runs whose numbers we publish are the runs nobody can look at — and the failures, which
are what the assignment means by inspectable, are the least reachable of all.
"""

from __future__ import annotations

import json

import pytest

from eval import bundles


class FakeRef:
    def __init__(self, aid, length, sha):
        self._d = {"artifact_id": aid, "kind": "dom", "source_url": "https://x/",
                   "sha256": sha, "length": length}

    def to_dict(self):
        return dict(self._d)


class FakeStore:
    """Artifacts as bytes, so sizes in the manifest are sizes and not assertions."""

    def __init__(self, blobs: dict[str, dict[str, bytes]]):
        self.blobs = blobs

    def artifacts_for_run(self, run_id):
        import hashlib
        return [FakeRef(aid, len(data), hashlib.sha256(data).hexdigest())
                for aid, data in self.blobs.get(run_id, {}).items()]

    def read_artifact(self, artifact_id):
        for run in self.blobs.values():
            if artifact_id in run:
                return run[artifact_id]
        return None


def _case(name, run_id, success, **kw):
    return {"case": name, "run_id": run_id, "counts_as_success": success,
            "terminal_status": "succeeded_verified" if success else "failed",
            "evidence": {"claims": 2, "independently_checked": 2}, **kw}


@pytest.fixture()
def sample(monkeypatch, tmp_path):
    path = tmp_path / "bundle-sample.json"
    path.write_text(json.dumps({"splits": {"dev": ["DEV-01"]}}))
    monkeypatch.setattr(bundles, "SAMPLE_FILE", path)
    return path


def test_every_failure_is_carried_and_the_named_success_with_it(tmp_path, sample):
    report = {"provenance": {"git_sha": "abc123"},
              "cases": [_case("DEV-01", "run_1", True), _case("DEV-02", "run_2", False),
                        _case("DEV-03", "run_3", True)]}
    store = FakeStore({"run_1": {"art_1": b"a" * 100},
                       "run_2": {"art_2": b"b" * 200},
                       "run_3": {"art_3": b"c" * 300}})

    manifest = bundles.export(report, "dev", store, tmp_path / "out")

    carried = {c["case"] for c in manifest["carried"]}
    assert carried == {"DEV-01", "DEV-02"}
    assert manifest["non_success_carried"] == manifest["non_success_total"] == 1
    # DEV-03 succeeded and was not named, so it is listed rather than silently absent.
    omitted = {o["case"]: o for o in manifest["omitted"]}
    assert set(omitted) == {"DEV-03"}
    assert "not required" in omitted["DEV-03"]["why_omitted"]
    assert omitted["DEV-03"]["artifacts"][0]["sha256"]
    assert omitted["DEV-03"]["verification"] == {"claims": 2, "independently_checked": 2}


def test_the_cap_is_applied_against_measured_sizes(tmp_path, sample):
    """A22.8: what exceeds the cap is decided by weighing, not by guessing."""
    report = {"provenance": {}, "cases": [_case("DEV-02", "run_2", False),
                                          _case("DEV-04", "run_4", False)]}
    store = FakeStore({"run_2": {"art_2": b"b" * 1024},
                       "run_4": {"art_4": b"d" * (4 * 1024 * 1024)}})

    manifest = bundles.export(report, "dev", store, tmp_path / "out", cap_mib=1.0)

    assert [c["case"] for c in manifest["carried"]] == ["DEV-02"]
    over = next(o for o in manifest["omitted"] if o["case"] == "DEV-04")
    assert over["why_omitted"] == "over the size cap"
    assert manifest["measured_bytes_carried"] == 1024


def test_a_sample_that_did_not_pass_is_reported_short_not_backfilled(tmp_path, sample):
    """Swapping in a case that happened to pass would make the sample a choice made after
    the round, which is the thing naming it in advance exists to prevent."""
    report = {"provenance": {}, "cases": [_case("DEV-01", "run_1", False),
                                          _case("DEV-03", "run_3", True)]}
    store = FakeStore({"run_1": {"art_1": b"a" * 10}, "run_3": {"art_3": b"c" * 10}})

    manifest = bundles.export(report, "dev", store, tmp_path / "out")

    assert manifest["sample_carried"] == ["DEV-01"]  # carried, but as a failure
    assert [c["reason"] for c in manifest["carried"]] == ["non-success run (A22.7)"]
    assert "DEV-03" in {o["case"] for o in manifest["omitted"]}


def test_the_bundle_is_re_hashed_on_the_way_out(tmp_path, sample):
    """A hash copied from the row that describes a file proves the row and the file agreed
    once, not that the copy a reader downloads is that file."""
    report = {"provenance": {}, "cases": [_case("DEV-02", "run_2", False)]}
    store = FakeStore({"run_2": {"art_2": b"payload"}})

    bundles.export(report, "dev", store, tmp_path / "out")

    written = json.loads((tmp_path / "out" / "DEV-02" / "case.json").read_text())
    ref = written["artifacts"][0]
    assert ref["sha256_matches"] is True
    assert (tmp_path / "out" / "DEV-02" / "art_2.bin").read_bytes() == b"payload"


def test_a_missing_sample_declaration_yields_no_sample_rather_than_an_invented_one(
        tmp_path, monkeypatch):
    monkeypatch.setattr(bundles, "SAMPLE_FILE", tmp_path / "absent.json")
    assert bundles.named_sample("dev") == []


def test_the_committed_sample_covers_the_splits_that_get_scored():
    declared = json.loads(bundles.SAMPLE_FILE.read_text(encoding="utf-8"))
    for split in ("dev", "experimental", "validation", "test"):
        assert declared["splits"][split], f"{split} has no pre-named success sample"
    assert "rule" in declared, "the rule that chose the sample is stated, not just the choice"


# ---- the public surface reaches them without the scored service being reachable ----

def _plant(root, name="dev-abc123-r1"):
    directory = root / "bundles" / name
    (directory / "DEV-02").mkdir(parents=True)
    (directory / "manifest.json").write_text(json.dumps({
        "split": "dev", "git_sha": "abc123", "cap_mib": 48, "measured_mib_carried": 0.01,
        "non_success_carried": 1, "non_success_total": 1, "sample_carried": ["DEV-01"],
        "sample_short_by": [], "omitted": [{"case": "DEV-03"}]}))
    (directory / "DEV-02" / "art_2.bin").write_bytes(b"payload")
    return directory


def test_the_public_service_lists_and_serves_a_committed_bundle(tmp_path, monkeypatch):
    from app.config import settings
    from app.server import app
    from fastapi.testclient import TestClient

    monkeypatch.setattr(type(settings), "eval_results_dir",
                        property(lambda self: tmp_path))
    _plant(tmp_path)
    client = TestClient(app)

    listing = client.get("/api/eval-bundles").json()
    entry = next(r for r in listing["rounds"] if r["round"] == "dev-abc123-r1")
    assert entry["non_success_carried"] == 1 and entry["omitted"] == 1

    assert client.get("/api/eval-bundles/dev-abc123-r1/manifest.json").status_code == 200
    blob = client.get("/api/eval-bundles/dev-abc123-r1/DEV-02/art_2.bin")
    assert blob.status_code == 200 and blob.content == b"payload"


@pytest.mark.parametrize("path", ["../runs.sqlite3", "dev-abc123-r1/../../runs.sqlite3",
                                  ".ssh/id_rsa", "dev-abc123-r1/DEV-02/../../../secret"])
def test_no_bundle_path_can_leave_the_bundle_root(tmp_path, monkeypatch, path):
    from app.config import settings
    from app.server import app
    from fastapi.testclient import TestClient

    monkeypatch.setattr(type(settings), "eval_results_dir",
                        property(lambda self: tmp_path))
    _plant(tmp_path)
    assert TestClient(app).get(f"/api/eval-bundles/{path}").status_code == 404

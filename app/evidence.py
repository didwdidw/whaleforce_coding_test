"""Evidence bundles (S-4.5).

One bundle per claim. It is deliberately not a link to a page "as it is now": it points at
the bytes we preserved at `retrieved_at`, with the hash of those exact bytes, because the
definition of `verified` (S-4.6) is a statement about a preserved artifact and nothing else.

The bundle records both anchors — the structural path and the label the value was bound to —
so a reader can re-run the binding by hand and disagree with us.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class EvidenceBundle:
    claim: str
    artifact_id: str
    source_url: str | None
    retrieved_at: float
    artifact_sha256: str
    #: The path deterministic code re-resolved inside the stored artifact.
    structural_anchor: str
    #: The label text the value is structurally bound to (S-4.9).
    label_anchor: str
    #: What the anchor resolved to, verbatim, before normalisation.
    extracted_span: str
    normalised_value: Any
    #: Trace step sequence numbers that produced the state this artifact captured.
    trace_segment: list[int] = field(default_factory=list)
    artifact_state: str = "stored"

    def to_dict(self) -> dict[str, Any]:
        return {
            "claim": self.claim,
            "artifact_id": self.artifact_id,
            "source_url": self.source_url,
            "retrieved_at": self.retrieved_at,
            "artifact_sha256": self.artifact_sha256,
            "artifact_state": self.artifact_state,
            "structural_anchor": self.structural_anchor,
            "label_anchor": self.label_anchor,
            "extracted_span": self.extracted_span,
            "normalised_value": self.normalised_value,
            "trace_segment": self.trace_segment,
        }

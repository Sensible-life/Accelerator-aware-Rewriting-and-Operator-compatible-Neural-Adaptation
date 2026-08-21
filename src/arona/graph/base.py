"""Common graph rewrite interface."""

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from arona.contracts.v1 import ArgMaxPostprocess, RewriteKind, RewriteRecord
from arona.onnx_frontend.loader import OnnxLoadResult


@dataclass(frozen=True)
class RewriteOutcome:
    """A rewrite decision and any artifacts produced by an applied candidate."""

    record: RewriteRecord
    optimized_model_path: Path | None = None
    postprocess_path: Path | None = None
    postprocess: ArgMaxPostprocess | None = None


class RewriteRule(Protocol):
    """Interface implemented by deterministic, target-aware graph rewrite rules."""

    rule_id: str
    kind: RewriteKind

    def apply(self, model: OnnxLoadResult, output_directory: Path) -> RewriteOutcome:
        """Evaluate the rule and write candidate artifacts only when it is safe."""

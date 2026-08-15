"""Common backend adapter protocol."""

from pathlib import Path
from typing import Protocol

from arona.contracts.v1 import BackendTarget, CompilationAnalysis, DeviceProbe, ValidationResult
from arona.onnx_frontend.loader import OnnxLoadResult


class BackendAdapter(Protocol):
    """Vendor compiler/runtime integration surface used by the ARONA pipeline."""

    name: str

    def probe(self) -> DeviceProbe:
        """Discover a selected target and its toolchain."""

    def compile(
        self,
        model: Path,
        output_directory: Path,
        timeout_seconds: int,
    ) -> Path:
        """Run the vendor compiler and return the captured compiler log path."""

    def parse(
        self,
        compiler_log: Path,
        model: OnnxLoadResult,
        target: BackendTarget,
    ) -> CompilationAnalysis:
        """Normalize compiler output into ARONA contracts."""

    def validate(self, artifacts_directory: Path) -> ValidationResult:
        """Run target validation when available."""

"""Baseline analysis pipeline."""

from datetime import UTC, datetime
from pathlib import Path

from arona.backends.stedgeai import StEdgeAiAdapter
from arona.contracts.v1 import (
    DeviceDiscovery,
    FeasibilityStatus,
    OptimizationDecision,
    RunReport,
    RunStatus,
)
from arona.onnx_frontend.loader import load_onnx_model_info


def discover_stedgeai() -> DeviceDiscovery:
    adapter = StEdgeAiAdapter()
    probe = adapter.probe()
    return DeviceDiscovery(
        generated_at=probe.generated_at,
        host=adapter.discover_host(),
        targets=[probe.target],
    )


def analyze_model(
    model_path: Path,
    compiler_log: Path,
    output_directory: Path,
) -> RunReport:
    """Analyze a model using a captured compiler log fixture."""

    now = datetime.now(UTC)
    output_directory.mkdir(parents=True, exist_ok=True)
    adapter = StEdgeAiAdapter()
    probe = adapter.probe()
    model = load_onnx_model_info(model_path)
    baseline = adapter.parse(compiler_log=compiler_log, model=model, target=probe.target)

    accepted = (
        baseline.resources is None or baseline.resources.deployable != FeasibilityStatus.INFEASIBLE
    )
    decision_reasons = ["Baseline analysis completed."]
    if (
        baseline.resources is not None
        and baseline.resources.deployable == FeasibilityStatus.INFEASIBLE
    ):
        decision_reasons.append("Compiler output is not deployable on the board memory profile.")

    return RunReport(
        run_id=now.strftime("%Y%m%dT%H%M%SZ-baseline"),
        status=RunStatus.COMPLETED,
        created_at=now,
        updated_at=now,
        target=probe.target,
        model=model.info,
        baseline=baseline,
        decision=OptimizationDecision(
            selected="baseline",
            accepted=accepted,
            reasons=decision_reasons,
        ),
    )

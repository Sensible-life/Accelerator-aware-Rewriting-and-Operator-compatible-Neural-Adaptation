"""Compiler-validated exact-rewrite optimization pipeline."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from arona.backends.base import BackendAdapter
from arona.backends.stedgeai import StEdgeAiAdapter
from arona.contracts.v1 import (
    ArtifactKind,
    ArtifactRef,
    BackendTarget,
    CompilationAnalysis,
    CompilationStatus,
    FeasibilityStatus,
    OptimizationDecision,
    RewriteRecord,
    RewriteStatus,
    RunReport,
    RunStatus,
    ValidationStatus,
)
from arona.graph import TerminalArgMaxRule
from arona.onnx_frontend.checksum import sha256_file
from arona.onnx_frontend.loader import OnnxLoadResult, load_onnx_model_info
from arona.validation import validate_externalized_argmax


def optimize_model(
    model_path: Path,
    output_directory: Path,
    *,
    baseline_compiler_log: Path | None = None,
    candidate_compiler_log: Path | None = None,
    validation_samples: int = 10,
    validation_seed: int = 260821,
    compile_timeout_seconds: int = 120,
    adapter: BackendAdapter | None = None,
) -> RunReport:
    """Apply a safe exact rewrite and keep it only after validation and compilation."""

    now = datetime.now(UTC)
    run_id = now.strftime("%Y%m%dT%H%M%SZ-optimize")
    run_directory = output_directory / run_id
    run_directory.mkdir(parents=True, exist_ok=True)

    selected_adapter = adapter or StEdgeAiAdapter()
    probe = selected_adapter.probe()
    baseline_model = load_onnx_model_info(model_path)
    baseline = _compile_or_parse(
        selected_adapter,
        baseline_model,
        probe.target,
        baseline_compiler_log,
        run_directory / "compiler" / "baseline",
        compile_timeout_seconds,
    )

    outcome = TerminalArgMaxRule().apply(baseline_model, run_directory)
    record = outcome.record
    optimized: CompilationAnalysis | None = None
    artifacts: list[ArtifactRef] = []
    reasons: list[str]
    selected: Literal["baseline", "optimized"] = "baseline"

    if outcome.optimized_model_path is None or outcome.postprocess is None:
        reasons = [f"Rewrite rejected: {record.reason}"]
    else:
        if record.candidate_model is not None:
            artifacts.append(record.candidate_model)
        if outcome.postprocess_path is not None:
            artifacts.append(_artifact(outcome.postprocess_path, ArtifactKind.OTHER))

        validation = validate_externalized_argmax(
            model_path,
            outcome.optimized_model_path,
            outcome.postprocess,
            run_directory / "validation.json",
            sample_count=validation_samples,
            seed=validation_seed,
        )
        if validation.artifact is not None:
            artifacts.append(validation.artifact)
        record = record.model_copy(update={"validation": validation})

        if validation.status != ValidationStatus.PASSED:
            reason = f"Validation did not pass: {validation.reason or validation.status}."
            record = _rolled_back(record, reason)
            reasons = [reason]
        else:
            candidate_model = load_onnx_model_info(outcome.optimized_model_path)
            optimized = _compile_or_parse(
                selected_adapter,
                candidate_model,
                probe.target,
                candidate_compiler_log,
                run_directory / "compiler" / "candidate",
                compile_timeout_seconds,
            ).model_copy(update={"analysis_id": "optimized-1"})
            record = record.model_copy(update={"candidate_analysis_id": optimized.analysis_id})
            improvements = _measured_improvements(baseline, optimized)
            if _analysis_accepted(optimized) and improvements:
                selected = "optimized"
                reasons = [
                    "ONNX Runtime equivalence validation passed.",
                    *improvements,
                ]
            else:
                if optimized.status != CompilationStatus.SUCCEEDED:
                    reason = "Candidate compiler analysis failed."
                elif not _analysis_accepted(optimized):
                    reason = "Candidate is infeasible for the board memory profile."
                else:
                    reason = "Candidate produced no measured compiler improvement."
                record = _rolled_back(record, reason)
                reasons = [reason]

    accepted_analysis = optimized if selected == "optimized" and optimized is not None else baseline
    decision = OptimizationDecision(
        selected=selected,
        accepted=_analysis_accepted(accepted_analysis),
        reasons=reasons,
        accelerator_node_ratio_delta=(
            optimized.graph.accelerator_node_ratio - baseline.graph.accelerator_node_ratio
            if optimized is not None
            else None
        ),
        accelerator_cpu_transitions_delta=(
            optimized.graph.accelerator_cpu_transitions - baseline.graph.accelerator_cpu_transitions
            if optimized is not None
            else None
        ),
        latency_mean_delta_ms=_latency_delta(baseline, optimized),
    )
    finished = datetime.now(UTC)
    return RunReport(
        run_id=run_id,
        status=RunStatus.COMPLETED,
        created_at=now,
        updated_at=finished,
        target=probe.target,
        model=baseline_model.info,
        baseline=baseline,
        optimized=optimized,
        rewrites=[record],
        decision=decision,
        artifacts=artifacts,
        diagnostics=[*baseline_model.diagnostics],
    )


def _compile_or_parse(
    adapter: BackendAdapter,
    model: OnnxLoadResult,
    target: BackendTarget,
    captured_log: Path | None,
    output_directory: Path,
    timeout_seconds: int,
) -> CompilationAnalysis:
    if captured_log is None:
        compiler_log = adapter.compile(
            Path(model.info.path),
            output_directory,
            timeout_seconds,
        )
    else:
        compiler_log = captured_log
    return adapter.parse(compiler_log, model, target)


def _analysis_accepted(analysis: CompilationAnalysis) -> bool:
    return analysis.status == CompilationStatus.SUCCEEDED and (
        analysis.resources is None or analysis.resources.deployable != FeasibilityStatus.INFEASIBLE
    )


def _measured_improvements(
    baseline: CompilationAnalysis,
    candidate: CompilationAnalysis,
) -> list[str]:
    improvements: list[str] = []
    if (
        baseline.status != CompilationStatus.SUCCEEDED
        and candidate.status == CompilationStatus.SUCCEEDED
    ):
        improvements.append("Compiler status improved from failed/partial to succeeded.")

    _append_decrease(
        improvements,
        "Software epochs",
        baseline.epochs.software_epochs,
        candidate.epochs.software_epochs,
    )
    _append_decrease(
        improvements,
        "Fallback operators",
        sum(operator.count for operator in baseline.fallback_operators),
        sum(operator.count for operator in candidate.fallback_operators),
    )
    _append_decrease(
        improvements,
        "NPU/CPU transitions",
        baseline.graph.accelerator_cpu_transitions,
        candidate.graph.accelerator_cpu_transitions,
    )

    baseline_activation = (
        baseline.resources.activation.total_bytes if baseline.resources is not None else None
    )
    candidate_activation = (
        candidate.resources.activation.total_bytes if candidate.resources is not None else None
    )
    _append_decrease(improvements, "Activation memory", baseline_activation, candidate_activation)

    baseline_deployable = baseline.resources.deployable if baseline.resources else None
    candidate_deployable = candidate.resources.deployable if candidate.resources else None
    if (
        baseline_deployable == FeasibilityStatus.INFEASIBLE
        and candidate_deployable != FeasibilityStatus.INFEASIBLE
    ):
        improvements.append("Board-memory deployability improved from infeasible.")
    return improvements


def _append_decrease(
    reasons: list[str],
    label: str,
    baseline: int | None,
    candidate: int | None,
) -> None:
    if baseline is not None and candidate is not None and candidate < baseline:
        reasons.append(f"{label} decreased: {baseline} -> {candidate}.")


def _rolled_back(record: RewriteRecord, reason: str) -> RewriteRecord:
    return record.model_copy(
        update={
            "status": RewriteStatus.ROLLED_BACK,
            "reason": f"{record.reason} Rolled back: {reason}",
        }
    )


def _latency_delta(
    baseline: CompilationAnalysis,
    candidate: CompilationAnalysis | None,
) -> float | None:
    if (
        candidate is None
        or baseline.performance is None
        or candidate.performance is None
        or baseline.performance.latency_mean_ms is None
        or candidate.performance.latency_mean_ms is None
    ):
        return None
    return candidate.performance.latency_mean_ms - baseline.performance.latency_mean_ms


def _artifact(path: Path, kind: ArtifactKind) -> ArtifactRef:
    return ArtifactRef(
        kind=kind,
        path=str(path),
        media_type="application/json",
        sha256=sha256_file(path),
        size_bytes=path.stat().st_size,
    )

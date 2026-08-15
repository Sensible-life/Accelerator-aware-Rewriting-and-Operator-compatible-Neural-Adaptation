"""ST Edge AI backend adapter implementation."""

from __future__ import annotations

import os
import platform
import shutil
import socket
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

from arona.analysis.memory import annotate_compiler_pools, has_address_overlap
from arona.backends.stedgeai.board_profiles import nucleo_n657x0_q_regions
from arona.backends.stedgeai.parsers import ParsedStEdgeAiLog, parse_stedgeai_log
from arona.contracts.v1 import (
    ArtifactKind,
    ArtifactRef,
    ActivationSummary,
    Availability,
    BackendCapabilities,
    BackendTarget,
    CompilationAnalysis,
    CompilationStatus,
    CompilerInvocation,
    DeviceInfo,
    DeviceProbe,
    Diagnostic,
    FeasibilityStatus,
    GraphSummary,
    HostEnvironment,
    ResourceAnalysis,
    Severity,
    StageStatus,
    ToolInfo,
    ToolchainInfo,
    ValidationResult,
    ValidationStatus,
)
from arona.onnx_frontend.loader import OnnxLoadResult


class StEdgeAiAdapter:
    """Adapter for the ST Edge AI Core ``stedgeai`` command."""

    name = "stedgeai"
    backend_version = "0.1.0"

    def probe(self) -> DeviceProbe:
        executable = shutil.which("stedgeai")
        version = _detect_version(executable) if executable else os.getenv("ARONA_STEDGEAI_VERSION")
        availability = Availability.AVAILABLE if executable or version else Availability.UNAVAILABLE
        warnings: list[str] = []
        if executable is None:
            warnings.append("stedgeai executable was not found on PATH.")

        target = BackendTarget(
            target_id="stedgeai:stm32n6:local",
            backend_name=self.name,
            backend_version=self.backend_version,
            availability=availability,
            device=DeviceInfo(
                device_id=os.getenv("ARONA_ST_DEVICE_ID", "unprobed"),
                vendor="STMicroelectronics",
                model="NUCLEO-N657X0-Q",
                accelerator="ST Neural-ART",
                connection="usb",
                address=os.getenv("ARONA_ST_CONNECTION"),
                firmware_version=os.getenv("ARONA_STLINK_VERSION"),
                metadata={
                    "boot_mode": os.getenv("ARONA_ST_BOOT_MODE"),
                    "board_revision": os.getenv("ARONA_ST_BOARD_REVISION"),
                },
            ),
            toolchain=ToolchainInfo(
                sdk=_tool("ST Edge AI Core", os.getenv("ARONA_ST_EDGE_AI_VERSION")),
                compiler=ToolInfo(
                    name="stedgeai",
                    version=version or "unavailable",
                    executable=executable or "stedgeai",
                ),
                runtime=_tool("X-CUBE-AI", os.getenv("ARONA_X_CUBE_AI_VERSION")),
                debugger=_tool(
                    "STM32CubeProgrammer",
                    os.getenv("ARONA_STM32CUBE_PROGRAMMER_VERSION"),
                ),
            ),
            capabilities=BackendCapabilities(
                input_formats=["onnx"],
                supports_compile=True,
                supports_node_placement=True,
                supports_cpu_fallback=True,
                supports_target_validation=True,
                supports_profiling=True,
            ),
            issues=warnings,
        )
        return DeviceProbe(
            generated_at=datetime.now(UTC),
            target=target,
            board_revision=os.getenv("ARONA_ST_BOARD_REVISION"),
            firmware_commit=os.getenv("ARONA_VALIDATION_FIRMWARE_COMMIT"),
            boot_mode=os.getenv("ARONA_ST_BOOT_MODE"),
            probe_status=availability,
            warnings=warnings,
        )

    def compile(self, model: Path, output_directory: Path, timeout_seconds: int = 120) -> Path:
        """Run ``stedgeai analyze`` and capture stdout/stderr in a log file."""

        executable = shutil.which("stedgeai")
        if executable is None:
            raise FileNotFoundError("stedgeai executable was not found on PATH")

        output_directory.mkdir(parents=True, exist_ok=True)
        log_path = output_directory / "stedgeai.log"
        command = [executable, "analyze", "--target", "stm32n6", "--model", str(model)]
        started = time.monotonic()
        completed = subprocess.run(
            command,
            cwd=output_directory,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            check=False,
        )
        duration_ms = (time.monotonic() - started) * 1000
        log_path.write_text(
            "\n".join(
                [
                    f"Command: {' '.join(command)}",
                    f"Exit code: {completed.returncode}",
                    f"Duration ms: {duration_ms:.3f}",
                    "STDOUT:",
                    completed.stdout,
                    "STDERR:",
                    completed.stderr,
                ]
            ),
            encoding="utf-8",
        )
        return log_path

    def parse(
        self,
        compiler_log: Path,
        model: OnnxLoadResult,
        target: BackendTarget,
    ) -> CompilationAnalysis:
        parsed = parse_stedgeai_log(compiler_log)
        resources = _resource_analysis(parsed)
        compiler = target.toolchain.compiler or ToolInfo(
            name="stedgeai",
            version="unknown",
            executable="stedgeai",
        )
        status = (
            CompilationStatus.FAILED
            if any(stage.status == StageStatus.FAILED for stage in parsed.deployment_stages)
            else CompilationStatus.SUCCEEDED
        )

        diagnostics = list(parsed.diagnostics)
        diagnostics.extend(resources.diagnostics)
        return CompilationAnalysis(
            analysis_id="baseline",
            status=status,
            model_sha256=model.info.sha256,
            compiler=compiler,
            invocation=CompilerInvocation(
                command=["stedgeai", "analyze", "--target", "stm32n6", "--model", model.info.path],
                working_directory=str(compiler_log.parent),
                exit_code=0 if status != CompilationStatus.FAILED else 1,
            ),
            deployment_stages=list(parsed.deployment_stages),
            graph=_graph_summary(model, parsed),
            epochs=parsed.epochs,
            fallback_operators=list(parsed.fallback_operators),
            qdq_boundaries=list(parsed.qdq_boundaries),
            nodes=[],
            partitions=[],
            resources=resources,
            artifacts=[
                ArtifactRef(
                    kind=ArtifactKind.COMPILER_LOG,
                    path=str(compiler_log),
                    media_type="text/plain",
                    description="Captured stedgeai compiler log",
                )
            ],
            diagnostics=diagnostics,
        )

    def validate(self, artifacts_directory: Path) -> ValidationResult:
        return ValidationResult(
            status=ValidationStatus.SKIPPED,
            reference_runtime="target",
            candidate_runtime="target",
            sample_count=0,
            absolute_tolerance=0.0,
            relative_tolerance=0.0,
            reason=f"Target validation is not implemented for {artifacts_directory}.",
        )

    def discover_host(self) -> HostEnvironment:
        return HostEnvironment(
            os=platform.platform(),
            architecture=platform.machine() or "unknown",
            python_version=sys.version.split()[0],
            hostname=socket.gethostname(),
        )


def _tool(name: str, version: str | None) -> ToolInfo | None:
    if version is None:
        return None
    return ToolInfo(name=name, version=version)


def _detect_version(executable: str) -> str | None:
    for args in ([executable, "--version"], [executable, "-v"]):
        try:
            completed = subprocess.run(
                args,
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
            )
        except (OSError, subprocess.SubprocessError):
            continue
        output = (completed.stdout or completed.stderr).strip()
        if output:
            return output.splitlines()[0]
    return None


def _resource_analysis(parsed: ParsedStEdgeAiLog) -> ResourceAnalysis:
    board_regions = nucleo_n657x0_q_regions()
    compiler_pools = annotate_compiler_pools(list(parsed.compiler_pools), board_regions)
    diagnostics: list[Diagnostic] = []
    for pool in compiler_pools:
        diagnostics.extend(pool.diagnostics)

    if has_address_overlap(board_regions):
        diagnostics.append(
            Diagnostic(
                severity=Severity.ERROR,
                source="memory.board_profile",
                message="Board memory regions overlap.",
                code="board_memory_overlap",
            )
        )

    deployable = (
        FeasibilityStatus.INFEASIBLE
        if any(pool.feasible == FeasibilityStatus.INFEASIBLE for pool in compiler_pools)
        else FeasibilityStatus.FEASIBLE
    )

    return ResourceAnalysis(
        board_regions=board_regions,
        compiler_pools=compiler_pools,
        storage_allocations=list(parsed.storage_allocations),
        activation=ActivationSummary(
            total_bytes=parsed.activation_total_bytes,
            accelerator_bytes=parsed.activation_accelerator_bytes,
            cpu_bytes=parsed.activation_cpu_bytes,
            largest_contiguous_buffer_bytes=parsed.largest_contiguous_buffer_bytes,
        ),
        deployable=deployable,
        diagnostics=diagnostics,
    )


def _graph_summary(model: OnnxLoadResult, parsed: ParsedStEdgeAiLog) -> GraphSummary:
    total_nodes = model.info.node_count
    fallback_nodes = sum(operator.count for operator in parsed.fallback_operators)
    cpu_nodes = min(total_nodes, fallback_nodes)
    accelerator_nodes = max(0, total_nodes - cpu_nodes)
    partition_count = 2 if cpu_nodes and accelerator_nodes else 1 if total_nodes else 0
    transitions = 1 if cpu_nodes and accelerator_nodes else 0
    return GraphSummary(
        total_nodes=total_nodes,
        accelerator_nodes=accelerator_nodes,
        cpu_nodes=cpu_nodes,
        unsupported_nodes=0,
        unknown_nodes=0,
        accelerator_node_ratio=(accelerator_nodes / total_nodes if total_nodes else 0.0),
        partition_count=partition_count,
        accelerator_cpu_transitions=transitions,
        estimated_boundary_transfer_bytes=sum(
            boundary.estimated_transfer_bytes or 0 for boundary in parsed.qdq_boundaries
        )
        or None,
    )

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

from arona.analysis.memory import (
    annotate_compiler_pools,
    annotate_storage_allocations,
    has_address_overlap,
)
from arona.backends.stedgeai.board_profiles import nucleo_n657x0_q_regions
from arona.backends.stedgeai.parsers import ParsedStEdgeAiLog, parse_stedgeai_log
from arona.contracts.v1 import (
    ActivationSummary,
    ArtifactKind,
    ArtifactRef,
    Availability,
    BackendCapabilities,
    BackendTarget,
    CompilationAnalysis,
    CompilationStatus,
    CompilerInvocation,
    ConnectionType,
    DeviceInfo,
    DeviceProbe,
    Diagnostic,
    FeasibilityStatus,
    GraphSummary,
    HostEnvironment,
    ResourceAnalysis,
    Severity,
    StageStatus,
    ToolchainInfo,
    ToolInfo,
    ValidationResult,
    ValidationStatus,
)
from arona.onnx_frontend.loader import OnnxLoadResult


class StEdgeAiAdapter:
    """Adapter for the ST Edge AI Core ``stedgeai`` command."""

    name = "stedgeai"
    backend_version = "0.1.0"

    def probe(self) -> DeviceProbe:
        path_executable = shutil.which("stedgeai")
        executable = _resolve_stedgeai_executable()
        version = _detect_version(executable) if executable else os.getenv("ARONA_STEDGEAI_VERSION")
        availability = Availability.AVAILABLE if executable or version else Availability.UNAVAILABLE
        warnings: list[str] = []
        if executable is None:
            warnings.append("stedgeai executable was not found.")
        elif path_executable is None:
            warnings.append(
                "stedgeai was found outside PATH; set ARONA_STEDGEAI_PATH or update PATH "
                f"to make the toolchain location explicit: {executable}"
            )

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
                connection=ConnectionType.USB,
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

        executable = _resolve_stedgeai_executable()
        if executable is None:
            raise FileNotFoundError(
                "stedgeai executable was not found; set ARONA_STEDGEAI_PATH or update PATH"
            )

        output_directory.mkdir(parents=True, exist_ok=True)
        log_path = output_directory / "stedgeai.log"
        command = [
            executable,
            "analyze",
            "--target",
            "stm32n6",
            "--model",
            str(model),
            "--type",
            "onnx",
            "--st-neural-art",
        ]
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
            if parsed.exit_code not in {None, 0}
            or any(stage.status == StageStatus.FAILED for stage in parsed.deployment_stages)
            or any(diagnostic.severity == Severity.ERROR for diagnostic in parsed.diagnostics)
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
                command=[
                    "stedgeai",
                    "analyze",
                    "--target",
                    "stm32n6",
                    "--model",
                    model.info.path,
                    "--type",
                    "onnx",
                    "--st-neural-art",
                ],
                working_directory=str(compiler_log.parent),
                exit_code=(
                    parsed.exit_code
                    if parsed.exit_code is not None
                    else (0 if status != CompilationStatus.FAILED else 1)
                ),
                duration_ms=parsed.duration_ms,
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


def _resolve_stedgeai_executable() -> str | None:
    """Find stedgeai from explicit configuration, PATH, or an X-CUBE-AI pack."""

    configured = os.getenv("ARONA_STEDGEAI_PATH")
    if configured:
        configured_path = Path(configured).expanduser()
        if configured_path.is_file():
            return str(configured_path.resolve())

    executable = shutil.which("stedgeai")
    if executable:
        return executable

    core_directory = os.getenv("STEDGEAI_CORE_DIR")
    if core_directory:
        candidate = Path(core_directory) / "Utilities" / "windows" / "stedgeai.exe"
        if candidate.is_file():
            return str(candidate.resolve())

    user_directory = Path(os.getenv("USERPROFILE", str(Path.home())))
    pack_root = (
        user_directory / "STM32Cube" / "Repository" / "Packs" / "STMicroelectronics" / "X-CUBE-AI"
    )
    candidates = list(pack_root.glob("*/Utilities/windows/stedgeai.exe"))
    if not candidates:
        return None
    newest = max(candidates, key=_xcube_ai_version_key)
    return str(newest.resolve())


def _xcube_ai_version_key(executable: Path) -> tuple[int, ...]:
    version = executable.parents[2].name
    return tuple(int(part) if part.isdigit() else -1 for part in version.split("."))


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
    storage_allocations = annotate_storage_allocations(
        list(parsed.storage_allocations),
        compiler_pools,
        board_regions,
    )
    diagnostics: list[Diagnostic] = []
    for pool in compiler_pools:
        diagnostics.extend(pool.diagnostics)
    for allocation in storage_allocations:
        diagnostics.extend(allocation.diagnostics)

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
        or any(
            allocation.feasible == FeasibilityStatus.INFEASIBLE
            for allocation in storage_allocations
        )
        else FeasibilityStatus.FEASIBLE
    )

    return ResourceAnalysis(
        board_regions=board_regions,
        compiler_pools=compiler_pools,
        storage_allocations=storage_allocations,
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

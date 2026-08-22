"""Compact terminal rendering for analysis results."""

from arona.contracts.v1 import CompilationAnalysis, DeviceDiscovery, RunReport, ToolInfo


def render_discovery(discovery: DeviceDiscovery) -> str:
    lines = ["Target environment"]
    for target in discovery.targets:
        device = target.device
        compiler = target.toolchain.compiler
        lines.extend(
            [
                f"  backend: {target.backend_name}",
                f"  status: {target.availability}",
                f"  board: {device.model if device else 'unknown'}",
                f"  accelerator: {device.accelerator if device else 'unknown'}",
                f"  compiler: {compiler.name if compiler else 'unknown'} "
                f"{compiler.version if compiler else ''}".rstrip(),
            ]
        )
        for issue in target.issues:
            lines.append(f"  warning: {issue}")
    return "\n".join(lines)


def render_run_report(report: RunReport) -> str:
    lines = [
        "Input model",
        f"  path: {report.model.path}",
        f"  checksum: sha256:{report.model.sha256}",
        f"  nodes: {report.model.node_count}",
        "",
        "Target environment",
        f"  backend: {report.target.backend_name}",
        f"  backend version: {report.target.backend_version}",
        f"  board: {report.target.device.model if report.target.device else 'unknown'}",
        f"  accelerator: {report.target.device.accelerator if report.target.device else 'unknown'}",
        f"  compiler: {_format_tool(report.target.toolchain.compiler)}",
        f"  debugger/programmer: {_format_tool(report.target.toolchain.debugger)}",
    ]
    if report.baseline is not None:
        lines.extend(["", *_render_analysis("Baseline", report.baseline)])
    if report.optimized is not None:
        lines.extend(["", *_render_analysis("Optimized candidate", report.optimized)])
    if report.rewrites:
        lines.extend(["", "Rewrites"])
        for rewrite in report.rewrites:
            validation = rewrite.validation.status if rewrite.validation else "not run"
            lines.append(f"  [{rewrite.status}] {rewrite.rule_id}; validation={validation}")
            lines.append(f"  reason: {rewrite.reason}")
    if report.decision is not None:
        lines.extend(
            [
                "",
                "Decision",
                f"  selected: {report.decision.selected}",
                f"  accepted: {report.decision.accepted}",
            ]
        )
        for reason in report.decision.reasons:
            lines.append(f"  reason: {reason}")
    if report.deployment is not None:
        lines.extend(
            [
                "",
                "Board deployment",
                f"  application: {report.deployment.application}",
                f"  board: {report.deployment.board}",
                f"  status: {report.deployment.status}",
                f"  serial port: {report.deployment.serial_port or 'unknown'}",
                f"  boot mode: {report.deployment.boot_mode or 'unknown'}",
            ]
        )
        if report.deployment.reason:
            lines.append(f"  reason: {report.deployment.reason}")
        if report.deployment.stages:
            lines.append("  stages:")
            for stage in report.deployment.stages:
                suffix = f" exit={stage.exit_code}" if stage.exit_code is not None else ""
                error = f" - {stage.first_error}" if stage.first_error else ""
                lines.append(f"    [{stage.status}] {stage.stage}{suffix}{error}")
        if report.deployment.observations:
            successful = sum(observation.success for observation in report.deployment.observations)
            latencies = [
                observation.latency_ms
                for observation in report.deployment.observations
                if observation.latency_ms is not None
            ]
            lines.append(
                f"  observations: {successful}/{len(report.deployment.observations)} succeeded"
            )
            if latencies:
                lines.append(
                    "  latency_ms: "
                    f"min={min(latencies):.3f} "
                    f"mean={sum(latencies) / len(latencies):.3f} "
                    f"max={max(latencies):.3f}"
                )
    return "\n".join(lines)


def _format_tool(tool: ToolInfo | None) -> str:
    if tool is None:
        return "unknown"
    return f"{tool.name} {tool.version}".strip()


def _render_analysis(label: str, analysis: CompilationAnalysis) -> list[str]:
    lines = [
        f"{label} pipeline",
        *[
            f"  [{stage.status}] {stage.stage}"
            + (f" - {stage.first_error}" if stage.first_error else "")
            for stage in analysis.deployment_stages
        ],
        "",
        "Placement",
        f"  epochs: total={analysis.epochs.total_epochs} "
        f"npu={analysis.epochs.accelerator_epochs} software={analysis.epochs.software_epochs}",
        f"  partitions: {analysis.graph.partition_count}",
        f"  accelerator/cpu transitions: {analysis.graph.accelerator_cpu_transitions}",
    ]
    if analysis.fallback_operators:
        lines.append("  fallback operators:")
        for operator in analysis.fallback_operators:
            reason = f" ({operator.reason})" if operator.reason else ""
            lines.append(f"    - {operator.op_type}: {operator.count}{reason}")

    if analysis.resources is not None:
        lines.extend(
            [
                "",
                "Memory",
                f"  deployable: {analysis.resources.deployable}",
                "  compiler pools:",
            ]
        )
        for pool in analysis.resources.compiler_pools:
            mapped = pool.mapped_region_name or "none"
            lines.append(
                f"    - {pool.name}: 0x{pool.start_address:08x} "
                f"{pool.size_bytes} B -> {mapped} [{pool.feasible}]"
            )
        activation = analysis.resources.activation
        lines.append(
            "  activation: "
            f"total={activation.total_bytes} "
            f"npu={activation.accelerator_bytes} "
            f"cpu={activation.cpu_bytes} "
            f"largest_contiguous={activation.largest_contiguous_buffer_bytes}"
        )
        if analysis.resources.diagnostics:
            lines.append("  diagnostics:")
            for diagnostic in analysis.resources.diagnostics:
                lines.append(f"    - [{diagnostic.severity}] {diagnostic.message}")
    return lines

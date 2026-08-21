"""Compact terminal rendering for analysis results."""

from arona.contracts.v1 import CompilationAnalysis, DeviceDiscovery, RunReport


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
        f"  board: {report.target.device.model if report.target.device else 'unknown'}",
        f"  accelerator: {report.target.device.accelerator if report.target.device else 'unknown'}",
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
    return "\n".join(lines)


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

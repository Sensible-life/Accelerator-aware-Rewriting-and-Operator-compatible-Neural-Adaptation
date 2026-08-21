"""Markdown report rendering."""

from arona.contracts.v1 import CompilationAnalysis, DeploymentResult, RunReport, ToolInfo


def render_markdown_report(report: RunReport) -> str:
    lines = [
        "# ARONA Analysis Report",
        "",
        "## Input Model",
        "",
        f"- Path: `{report.model.path}`",
        f"- SHA-256: `{report.model.sha256}`",
        f"- Nodes: {report.model.node_count}",
        "",
        "## Target",
        "",
        f"- Backend: `{report.target.backend_name}`",
        f"- Backend version: `{report.target.backend_version}`",
        f"- Board: `{report.target.device.model if report.target.device else 'unknown'}`",
        (
            "- Accelerator: "
            f"`{report.target.device.accelerator if report.target.device else 'unknown'}`"
        ),
        (f"- SDK: `{_format_tool(report.target.toolchain.sdk)}`"),
        (f"- Compiler: `{_format_tool(report.target.toolchain.compiler)}`"),
        (f"- Debugger/programmer: `{_format_tool(report.target.toolchain.debugger)}`"),
    ]
    if report.baseline is not None:
        lines.extend(_render_analysis("Baseline", report.baseline))
    if report.optimized is not None:
        lines.extend(_render_analysis("Optimized Candidate", report.optimized))

    if report.rewrites:
        lines.extend(
            [
                "",
                "## Rewrite and Validation",
                "",
                "| Rule | Status | Nodes | Validation | Reason |",
                "| --- | --- | --- | --- | --- |",
            ]
        )
        for rewrite in report.rewrites:
            validation = rewrite.validation.status if rewrite.validation else "not run"
            nodes = ", ".join(rewrite.affected_node_ids)
            lines.append(
                f"| `{rewrite.rule_id}` | `{rewrite.status}` | `{nodes}` | "
                f"`{validation}` | {rewrite.reason} |"
            )

    if report.decision is not None:
        lines.extend(
            [
                "",
                "## Final Decision",
                "",
                f"- Selected: `{report.decision.selected}`",
                f"- Accepted for deployment: `{report.decision.accepted}`",
            ]
        )
        lines.extend(f"- Reason: {reason}" for reason in report.decision.reasons)

    if report.deployment is not None:
        lines.extend(_render_deployment(report.deployment))
    return "\n".join(lines) + "\n"


def _render_analysis(label: str, analysis: CompilationAnalysis) -> list[str]:
    lines = [
        "",
        f"## {label} Compiler Analysis",
        "",
        f"Status: `{analysis.status}`",
        "",
        "| Metric | Value |",
        "| --- | ---: |",
        f"| Total epochs | {analysis.epochs.total_epochs} |",
        f"| NPU epochs | {analysis.epochs.accelerator_epochs} |",
        f"| Software epochs | {analysis.epochs.software_epochs} |",
        f"| Fallback operators | {sum(item.count for item in analysis.fallback_operators)} |",
        f"| Partitions | {analysis.graph.partition_count} |",
        f"| NPU/CPU transitions | {analysis.graph.accelerator_cpu_transitions} |",
        "",
        "### Fallback Operators",
        "",
        "| Operator | Count | Reason |",
        "| --- | ---: | --- |",
    ]
    for operator in analysis.fallback_operators:
        lines.append(f"| `{operator.op_type}` | {operator.count} | {operator.reason or ''} |")

    if analysis.resources is not None:
        lines.extend(
            [
                "",
                "### Memory Feasibility",
                "",
                f"Deployable: `{analysis.resources.deployable}`",
                "",
                "| Compiler Pool | Address | Size | Board Region | Feasible |",
                "| --- | ---: | ---: | --- | --- |",
            ]
        )
        for pool in analysis.resources.compiler_pools:
            lines.append(
                f"| `{pool.name}` | `0x{pool.start_address:08x}` | {pool.size_bytes} | "
                f"{pool.mapped_region_name or ''} | `{pool.feasible}` |"
            )
    return lines


def _render_deployment(deployment: DeploymentResult) -> list[str]:
    lines = [
        "",
        "## Board Deployment",
        "",
        f"- Application: `{deployment.application}`",
        f"- Board: `{deployment.board}`",
        f"- Status: `{deployment.status}`",
        f"- Serial port: `{deployment.serial_port or 'unknown'}`",
        f"- Boot mode: `{deployment.boot_mode or 'unknown'}`",
    ]
    if deployment.reason:
        lines.append(f"- Reason: {deployment.reason}")

    artifacts = [artifact for artifact in [deployment.model, *deployment.firmware] if artifact]
    if artifacts:
        lines.extend(
            [
                "",
                "### Deployment Artifacts",
                "",
                "| Kind | Path | SHA-256 | Size bytes |",
                "| --- | --- | --- | ---: |",
            ]
        )
        for artifact in artifacts:
            lines.append(
                f"| `{artifact.kind}` | `{artifact.path}` | "
                f"`{artifact.sha256 or ''}` | {artifact.size_bytes or ''} |"
            )

    if deployment.stages:
        lines.extend(
            [
                "",
                "### Deployment Stages",
                "",
                "| Stage | Status | Exit Code | Duration ms | First Error |",
                "| --- | --- | ---: | ---: | --- |",
            ]
        )
        for stage in deployment.stages:
            lines.append(
                f"| `{stage.stage}` | `{stage.status}` | "
                f"{stage.exit_code if stage.exit_code is not None else ''} | "
                f"{stage.duration_ms if stage.duration_ms is not None else ''} | "
                f"{stage.first_error or ''} |"
            )

    if deployment.observations:
        latencies = [
            observation.latency_ms
            for observation in deployment.observations
            if observation.latency_ms is not None
        ]
        lines.extend(
            [
                "",
                "### Target Observations",
                "",
                "- Successful observations: "
                f"{sum(item.success for item in deployment.observations)}"
                f"/{len(deployment.observations)}",
            ]
        )
        if latencies:
            lines.extend(
                [
                    f"- Latency min ms: {min(latencies):.3f}",
                    f"- Latency mean ms: {sum(latencies) / len(latencies):.3f}",
                    f"- Latency max ms: {max(latencies):.3f}",
                ]
            )
    return lines


def _format_tool(tool: ToolInfo | None) -> str:
    if tool is None:
        return "unknown"
    return f"{tool.name} {tool.version}".strip()

"""Markdown report rendering."""

from arona.contracts.v1 import RunReport


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
        f"- Board: `{report.target.device.model if report.target.device else 'unknown'}`",
        (
            "- Accelerator: "
            f"`{report.target.device.accelerator if report.target.device else 'unknown'}`"
        ),
    ]
    if report.baseline is not None:
        baseline = report.baseline
        lines.extend(
            [
                "",
                "## Baseline Placement",
                "",
                "| Metric | Value |",
                "| --- | --- |",
                f"| Total epochs | {baseline.epochs.total_epochs} |",
                f"| NPU epochs | {baseline.epochs.accelerator_epochs} |",
                f"| Software epochs | {baseline.epochs.software_epochs} |",
                f"| Partitions | {baseline.graph.partition_count} |",
                f"| NPU/CPU transitions | {baseline.graph.accelerator_cpu_transitions} |",
                "",
                "## Fallback Operators",
                "",
                "| Operator | Count | Reason |",
                "| --- | ---: | --- |",
            ]
        )
        for operator in baseline.fallback_operators:
            lines.append(f"| `{operator.op_type}` | {operator.count} | {operator.reason or ''} |")

        if baseline.resources is not None:
            lines.extend(
                [
                    "",
                    "## Memory Feasibility",
                    "",
                    f"Deployable: `{baseline.resources.deployable}`",
                    "",
                    "| Compiler Pool | Address | Size | Board Region | Feasible |",
                    "| --- | ---: | ---: | --- | --- |",
                ]
            )
            for pool in baseline.resources.compiler_pools:
                lines.append(
                    f"| `{pool.name}` | `0x{pool.start_address:08x}` | {pool.size_bytes} | "
                    f"{pool.mapped_region_name or ''} | `{pool.feasible}` |"
                )
            lines.extend(["", "### Storage Classes", "", "| Class | Region | Size | Feasible |"])
            lines.append("| --- | --- | ---: | --- |")
            for allocation in baseline.resources.storage_allocations:
                lines.append(
                    f"| `{allocation.storage_class}` | `{allocation.region_name}` | "
                    f"{allocation.size_bytes} | `{allocation.feasible}` |"
                )
    return "\n".join(lines) + "\n"

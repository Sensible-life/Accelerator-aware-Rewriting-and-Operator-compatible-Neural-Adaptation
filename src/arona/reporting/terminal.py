"""Compact terminal rendering for analysis and deployment results."""

import os
import sys

from arona.contracts.v1 import (
    CompilationAnalysis,
    DeploymentResult,
    DeviceDiscovery,
    RunReport,
    ToolInfo,
)

RESET = "\x1b[0m"
ARONA_ORANGE = "\x1b[38;2;222;112;74m"
ARONA_GOLD = "\x1b[38;2;246;190;99m"
ARONA_CYAN = "\x1b[38;2;108;210;235m"
ARONA_BLUE = "\x1b[38;2;125;156;222m"
ARONA_LILAC = "\x1b[38;2;181;148;244m"
ARONA_CLOUD = "\x1b[38;2;136;153;166m"
ARONA_TEXT = "\x1b[38;2;246;149;105m"
ARONA_DIM = "\x1b[38;2;139;139;139m"
ARONA_OK = "\x1b[38;2;101;213;139m"
ARONA_WARN = "\x1b[38;2;246;190;99m"
ARONA_FAIL = "\x1b[38;2;242;97;97m"

ARONA_SCENE = [
    "Welcome to ARONA",
    "................................................................",
    "",
    "        *                                  █████▓▓░",
    "                            *           ███▓░    ░░",
    "      ░░░░░                              ██▓░",
    "   ░░░░░░░░░░░              ONNX          ██▓░░     ▓",
    "  ░░░░░░░░░░░░░░                          ░▓▓███▓▓░",
    "",
    "                         ░░░░",
    "                       ░░░░░░░░",
    "                    ░░░░░░░░░░░░░░",
    "",
    "      █████████                         Neural-ART",
    "     ██▄█████▄██             *",
    "      █████████        NPU",
    "......█ █...█ █..................................................",
    "",
    " Let's get started.",
    "",
    " Run arona doctor to check your board/toolchain.",
    " Run arona optimize <model> --target stedgeai --deploy to validate on target.",
]

ARONA_PLAIN_SCENE = [
    "Welcome to ARONA",
    "................................................................",
    "",
    "        *                                  #######",
    "                            *           ###      ##",
    "      ......                              ##",
    "   ...........              ONNX          ##       #",
    "  .............                           #######",
    "",
    "                         ....",
    "                       ........",
    "                    ..............",
    "",
    "      #########                         Neural-ART",
    "     ##-#####-##             *",
    "      #########        NPU",
    "......# #...# #..................................................",
    "",
    " Let's get started.",
    "",
    " Run arona doctor to check your board/toolchain.",
    " Run arona optimize <model> --target stedgeai --deploy to validate on target.",
]


def render_banner(subtitle: str | None = None) -> list[str]:
    lines = _render_plain_banner() if _plain_banner_requested() else _render_scene_banner()
    if subtitle:
        lines.extend(["", subtitle])
    return lines


def _render_scene_banner() -> list[str]:
    return [
        _paint_scene_line(line)
        for line in ARONA_SCENE
    ]


def _render_plain_banner() -> list[str]:
    return [*ARONA_PLAIN_SCENE]


def _paint_scene_line(line: str) -> str:
    if line.startswith("Welcome"):
        return f"{ARONA_TEXT}{line}{RESET}"
    if set(line) <= {"."}:
        return f"{ARONA_DIM}{line}{RESET}"
    if "Run arona" in line or "Let's get started" in line:
        return f"{ARONA_DIM}{line}{RESET}"

    painted = line
    if "██" in painted:
        for token in ("█", "▓", "▄"):
            painted = painted.replace(token, _paint(token, ARONA_ORANGE))
    if "░" in painted:
        painted = painted.replace("░", _paint("░", ARONA_CLOUD))
    painted = painted.replace("*", _paint("*", ARONA_GOLD))
    painted = painted.replace("ONNX", _paint("ONNX", ARONA_CYAN))
    painted = painted.replace("NPU", _paint("NPU", ARONA_GOLD))
    painted = painted.replace("Neural-ART", _paint("Neural-ART", ARONA_LILAC))
    return painted


def _paint(text: str, color: str) -> str:
    return f"{color}{text}{RESET}"


def _plain_banner_requested() -> bool:
    if os.getenv("ARONA_UNICODE"):
        return False
    if os.getenv("NO_COLOR") or os.getenv("ARONA_PLAIN_BANNER"):
        return True
    encoding = sys.stdout.encoding or "utf-8"
    try:
        "\n".join(ARONA_SCENE).encode(encoding)
    except UnicodeEncodeError:
        return True
    return False


def render_discovery(discovery: DeviceDiscovery) -> str:
    lines = [*render_banner("Target environment")]
    for target in discovery.targets:
        device = target.device
        compiler = target.toolchain.compiler
        status_icon = _status_icon(target.availability)
        lines.extend(
            [
                f"  {status_icon} backend: {target.backend_name}",
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
        *render_banner(),
        "",
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
            lines.append(
                f"  {_status_icon(rewrite.status)} [{rewrite.status}] "
                f"{rewrite.rule_id}; validation={validation}"
            )
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
        lines.extend(["", *render_deployment_block(report.deployment, title="Board deployment")])
    return "\n".join(lines)


def render_deployment_block(
    result: DeploymentResult, *, title: str = "STM32N6 deployment"
) -> list[str]:
    lines = [
        title,
        f"  application: {result.application}",
        f"  board: {result.board}",
        f"  status: {result.status}",
        f"  serial port: {result.serial_port or 'unknown'}",
        f"  boot mode: {result.boot_mode or 'unknown'}",
    ]
    if result.reason:
        lines.append(f"  reason: {result.reason}")
    if result.stages:
        lines.append("  stages:")
        for stage in result.stages:
            suffix = f" exit={stage.exit_code}" if stage.exit_code is not None else ""
            error = f" - {stage.first_error}" if stage.first_error else ""
            lines.append(
                f"    {_status_icon(stage.status)} [{stage.status}] {stage.stage}{suffix}{error}"
            )
    lines.append(f"  inference observations: {len(result.observations)}")
    if result.observations:
        successful = sum(observation.success for observation in result.observations)
        latencies = [
            observation.latency_ms
            for observation in result.observations
            if observation.latency_ms is not None
        ]
        lines.append(f"  observations: {successful}/{len(result.observations)} succeeded")
        if latencies:
            lines.append(
                "  latency_ms: "
                f"min={min(latencies):.3f} "
                f"mean={sum(latencies) / len(latencies):.3f} "
                f"max={max(latencies):.3f}"
            )
    return lines


def _format_tool(tool: ToolInfo | None) -> str:
    if tool is None:
        return "unknown"
    return f"{tool.name} {tool.version}".strip()


def _render_analysis(label: str, analysis: CompilationAnalysis) -> list[str]:
    lines = [
        f"{label} pipeline",
        *[
            f"  {_status_icon(stage.status)} [{stage.status}] {stage.stage}"
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


def _status_icon(status: object) -> str:
    value = str(status)
    if value in {"available", "succeeded", "applied", "passed", "feasible"}:
        return _paint("OK", ARONA_OK) if _color_enabled() else "OK"
    if value in {"warning", "partial", "skipped"}:
        return _paint("!", ARONA_WARN) if _color_enabled() else "!"
    if value in {"failed", "unavailable", "rejected", "rolled_back", "infeasible"}:
        return _paint("FAIL", ARONA_FAIL) if _color_enabled() else "FAIL"
    return "-"


def _color_enabled() -> bool:
    return not _plain_banner_requested()

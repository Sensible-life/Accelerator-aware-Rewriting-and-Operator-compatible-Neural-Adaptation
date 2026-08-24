"""Compact terminal rendering for analysis and deployment results."""

import os
import re
import shutil
import sys
import textwrap
from collections.abc import Sequence
from typing import TextIO

from arona.contracts.v1 import (
    CompilationAnalysis,
    DeploymentResult,
    DeviceDiscovery,
    RunReport,
    ToolInfo,
)

RESET = "\x1b[0m"
ARONA_BLUE = "\x1b[38;2;78;168;215m"
ARONA_PINK = "\x1b[38;2;215;111;159m"
ARONA_DIM = "\x1b[38;2;139;139;139m"
ARONA_OK = "\x1b[38;2;101;213;139m"
ARONA_WARN = "\x1b[38;2;246;190;99m"
ARONA_FAIL = "\x1b[38;2;242;97;97m"

ANSI_PATTERN = re.compile(r"\x1b\[[0-9;]*m")

ARONA_SCENE = [
    "Welcome to ARONA",
    "......................................................................",
    "",
    "  ONNX MODEL",
    "      ◇",
    "      │",
    "      ╰───────────▶ ╭─┬──────────────────────┬─╮",
    "                    ├─┤      A R O N A       ├─┤ ─────▶ EDGE TARGET",
    "                    ├─┤ rewrite · map · tune ├─┤           ◆",
    "                    ╰─┴──────────┬───────────┴─╯",
    "                                 ▼  Neural-ART / NPU",
    "......................................................................",
    "",
    " Let's get started.",
    "",
    " Run arona doctor to check your board/toolchain.",
    " Run arona optimize <model> --target stedgeai --deploy to validate on target.",
]

ARONA_PLAIN_SCENE = [
    "Welcome to ARONA",
    "......................................................................",
    "",
    "  ONNX MODEL",
    "      o",
    "      |",
    "      `-----------> +-+----------------------+-+",
    "                    | |      A R O N A       | | -----> EDGE TARGET",
    "                    | | rewrite . map . tune | |           *",
    "                    +-+----------+-----------+-+",
    "                                 v  Neural-ART / NPU",
    "......................................................................",
    "",
    " Let's get started.",
    "",
    " Run arona doctor to check your board/toolchain.",
    " Run arona optimize <model> --target stedgeai --deploy to validate on target.",
]


def render_banner(subtitle: str | None = None) -> list[str]:
    lines = _render_plain_banner() if _plain_banner_requested() else _render_scene_banner()
    if subtitle:
        lines.extend(["", render_heading(subtitle)])
    return lines


def _render_scene_banner() -> list[str]:
    return [_paint_scene_line(line) for line in ARONA_SCENE]


def _render_plain_banner() -> list[str]:
    return [*ARONA_PLAIN_SCENE]


def _paint_scene_line(line: str) -> str:
    if line == "Welcome to ARONA":
        return _paint("Welcome to ", ARONA_BLUE) + _paint("ARONA", ARONA_PINK)
    if line and set(line) <= {".", "─"}:
        return _paint(line, ARONA_DIM)
    if "A R O N A" in line:
        before, brand, after = line.partition("A R O N A")
        return _paint(before, ARONA_BLUE) + _paint(brand, ARONA_PINK) + _paint(after, ARONA_BLUE)
    if "rewrite" in line:
        before, operations, after = line.partition("rewrite · map · tune")
        return (
            _paint(before, ARONA_BLUE) + _paint(operations, ARONA_DIM) + _paint(after, ARONA_BLUE)
        )
    if "INSPECT" in line:
        return _paint(line, ARONA_DIM)
    if "Neural-ART" in line:
        before, target, after = line.partition("Neural-ART / NPU")
        return before + _paint(target, ARONA_PINK) + after
    if "Let's get started" in line or "Run arona" in line:
        return _paint(line, ARONA_DIM)
    return _paint(line, ARONA_BLUE)


def _paint(text: str, color: str) -> str:
    if not terminal_color_enabled():
        return text
    return f"{color}{text}{RESET}"


def _plain_banner_requested() -> bool:
    if _env_enabled("ARONA_UNICODE"):
        return False
    if _env_enabled("ARONA_PLAIN_BANNER"):
        return True
    encoding = sys.stdout.encoding or "utf-8"
    try:
        "\n".join(ARONA_SCENE).encode(encoding)
    except UnicodeEncodeError:
        return True
    return False


def terminal_color_enabled(stream: TextIO | None = None) -> bool:
    """Return whether terminal output should contain ANSI colors."""

    if "ARONA_COLOR" in os.environ:
        return _env_enabled("ARONA_COLOR")
    if "NO_COLOR" in os.environ:
        return False
    if _env_enabled("FORCE_COLOR") or _env_enabled("CLICOLOR_FORCE"):
        return True
    output = stream or sys.stdout
    return bool(getattr(output, "isatty", lambda: False)()) and os.getenv("TERM") != "dumb"


def write_terminal(message: str, stream: TextIO | None = None) -> None:
    """Write rendered output without Click stripping 24-bit ANSI colors on Windows."""

    output = stream or sys.stdout
    if output is sys.stdout and terminal_color_enabled(output):
        _enable_windows_virtual_terminal(output)
    output.write(message)
    output.write("\n")
    output.flush()


def _enable_windows_virtual_terminal(stream: TextIO) -> None:
    if os.name != "nt" or not hasattr(stream, "fileno"):
        return
    try:
        import ctypes
        import msvcrt
        from ctypes import wintypes

        handle = msvcrt.get_osfhandle(stream.fileno())
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.GetConsoleMode.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
        kernel32.GetConsoleMode.restype = wintypes.BOOL
        kernel32.SetConsoleMode.argtypes = [wintypes.HANDLE, wintypes.DWORD]
        kernel32.SetConsoleMode.restype = wintypes.BOOL
        mode = wintypes.DWORD()
        if kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
            kernel32.SetConsoleMode(handle, mode.value | 0x0004)
    except (ImportError, OSError, ValueError):
        return


def _env_enabled(name: str) -> bool:
    value = os.getenv(name)
    return value is not None and value.strip().lower() not in {"", "0", "false", "no", "off"}


def render_heading(text: str) -> str:
    """Render a primary CLI section heading using ARONA's text color."""

    return _paint(text, ARONA_BLUE)


def render_accent(text: str) -> str:
    """Render emphasized CLI text using ARONA's accent color."""

    return _paint(text, ARONA_PINK)


def render_command_header(
    command: str,
    description: str | None = None,
    *,
    scene: bool = False,
) -> list[str]:
    """Render a consistent identity and description for an ARONA command."""

    lines = render_banner() if scene and not _env_enabled("ARONA_INTERACTIVE_CHILD") else []
    if lines:
        lines.append("")
    lines.append(f"{render_heading('ARONA')}  {render_accent(command)}")
    if description:
        lines.append(_paint(description, ARONA_DIM))
    return lines


def render_key_values(title: str, items: list[tuple[str, object]]) -> list[str]:
    """Render aligned key/value rows under a colored section heading."""

    if not items:
        return [render_heading(title)]
    width = max(len(key) + 1 for key, _ in items)
    lines = [render_heading(title)]
    for key, value in items:
        label = _paint(f"{key}:".ljust(width), ARONA_DIM)
        lines.append(f"  {label}  {value}")
    return lines


def render_numbered_list(title: str, items: list[str]) -> list[str]:
    """Render a short ordered list for user actions or generated artifacts."""

    lines = [render_heading(title)]
    lines.extend(f"  {render_accent(str(index))}. {item}" for index, item in enumerate(items, 1))
    return lines


def render_progress_step(
    index: int,
    total: int,
    label: str,
    status: object,
    detail: str | None = None,
) -> str:
    """Render one numbered pipeline step with a semantic status marker."""

    suffix = f"  {_paint(detail, ARONA_DIM)}" if detail else ""
    return f"  {render_status_icon(status)} {render_accent(f'{index}/{total}')} {label}{suffix}"


def render_pipeline_tracker(
    stages: Sequence[tuple[str, object]],
    title: str = "Deployment pipeline",
) -> list[str]:
    """Render the end-to-end ARONA workflow as a vertical state tracker."""

    lines = [render_heading(title)]
    plain = _plain_banner_requested()
    connector = "  |" if plain else "  │"
    for index, (label, status) in enumerate(stages):
        value = str(status)
        if value == "running":
            icon = _paint(">" if plain else "◆", ARONA_PINK)
            suffix = f"  {_paint('Running', ARONA_PINK)}"
        elif value == "pending":
            icon = _paint("o" if plain else "○", ARONA_DIM)
            suffix = ""
        else:
            icon = render_status_icon(status)
            suffix = ""
        lines.append(f"  {icon} {label}{suffix}")
        if index < len(stages) - 1:
            lines.append(_paint(connector, ARONA_DIM))
    return lines


def render_pipeline_overview(
    stages: Sequence[tuple[str, object]],
    title: str = "Workflow",
) -> str:
    """Render a compact single-line pipeline for the workspace dashboard."""

    plain = _plain_banner_requested()
    connector = " - " if plain else " ─ "
    rendered: list[str] = []
    for label, status in stages:
        value = str(status)
        if value == "running":
            icon = _paint(">" if plain else "◆", ARONA_PINK)
        elif value == "pending":
            icon = _paint("o" if plain else "○", ARONA_DIM)
        else:
            icon = render_status_icon(status)
        rendered.append(f"{icon} {label}")
    return f"{render_heading(title)}  {connector.join(rendered)}"


def render_notice(title: str, lines: list[str], status: object = "succeeded") -> list[str]:
    """Render a bordered result, warning, or next-action notice."""

    label = f"{render_status_icon(status)} {title}"
    maximum_width = max(28, min(76, shutil.get_terminal_size((80, 24)).columns - 4))
    content = [
        wrapped for line in (lines or [""]) for wrapped in _wrap_visible_line(line, maximum_width)
    ]
    width = max(28, _visible_length(label), *(_visible_length(line) for line in content))
    horizontal = "-" if _plain_banner_requested() else "─"
    vertical = "|" if _plain_banner_requested() else "│"
    top_left, top_right, bottom_left, bottom_right = (
        ("+", "+", "+", "+") if _plain_banner_requested() else ("╭", "╮", "╰", "╯")
    )
    top_fill = max(1, width - _visible_length(label) - 1)
    rendered = [
        _paint(f"{top_left}{horizontal} ", ARONA_DIM)
        + label
        + _paint(f" {horizontal * top_fill}{top_right}", ARONA_DIM)
    ]
    for line in content:
        padding = " " * (width - _visible_length(line))
        rendered.append(
            _paint(vertical, ARONA_DIM) + f" {line}{padding} " + _paint(vertical, ARONA_DIM)
        )
    rendered.append(_paint(f"{bottom_left}{horizontal * (width + 2)}{bottom_right}", ARONA_DIM))
    return rendered


def render_action_result(command: str, action: str, path: str) -> str:
    """Render a compact success result for file-mutating deployment helpers."""

    lines = [
        *render_command_header(command),
        "",
        *render_notice(action, [f"Path  {path}"]),
    ]
    return "\n".join(lines)


def _visible_length(text: str) -> int:
    return len(ANSI_PATTERN.sub("", text))


def _wrap_visible_line(text: str, width: int) -> list[str]:
    if _visible_length(text) <= width or ANSI_PATTERN.search(text):
        return [text]
    return textwrap.wrap(
        text,
        width=width,
        break_long_words=True,
        break_on_hyphens=False,
        subsequent_indent="  ",
    ) or [""]


def render_discovery(discovery: DeviceDiscovery) -> str:
    lines = [
        *render_command_header(
            "Discover",
            "Inspect the local compiler and accelerator target.",
            scene=True,
        )
    ]
    for target in discovery.targets:
        device = target.device
        compiler = target.toolchain.compiler
        lines.extend(
            [
                "",
                *render_key_values(
                    "Target environment",
                    [
                        (
                            "backend",
                            f"{render_status_icon(target.availability)} {target.backend_name}",
                        ),
                        ("status", target.availability),
                        ("board", device.model if device else "unknown"),
                        ("accelerator", device.accelerator if device else "unknown"),
                        (
                            "compiler",
                            f"{compiler.name if compiler else 'unknown'} "
                            f"{compiler.version if compiler else ''}".rstrip(),
                        ),
                    ],
                ),
            ]
        )
        for issue in target.issues:
            lines.extend(["", *render_notice("Needs attention", [issue], "warning")])
    return "\n".join(lines)


def render_run_report(report: RunReport, *, command: str = "Run report") -> str:
    lines = [
        *render_command_header(
            command,
            "Compiler-validated ONNX analysis and target deployment evidence.",
            scene=True,
        ),
        "",
        *render_key_values(
            "Input model",
            [
                ("path", report.model.path),
                ("checksum", f"sha256:{report.model.sha256}"),
                ("nodes", report.model.node_count),
            ],
        ),
        "",
        *render_key_values(
            "Target environment",
            [
                ("backend", report.target.backend_name),
                ("backend version", report.target.backend_version),
                ("board", report.target.device.model if report.target.device else "unknown"),
                (
                    "accelerator",
                    report.target.device.accelerator if report.target.device else "unknown",
                ),
                ("compiler", _format_tool(report.target.toolchain.compiler)),
                ("debugger/programmer", _format_tool(report.target.toolchain.debugger)),
            ],
        ),
    ]
    if report.baseline is not None:
        lines.extend(["", *_render_analysis("Baseline", report.baseline)])
    if report.optimized is not None:
        lines.extend(["", *_render_analysis("Optimized candidate", report.optimized)])
    if report.rewrites:
        lines.extend(["", render_heading("Rewrites")])
        for rewrite in report.rewrites:
            validation = rewrite.validation.status if rewrite.validation else "not run"
            lines.append(
                f"  {render_status_icon(rewrite.status)} [{rewrite.status}] "
                f"{rewrite.rule_id}; validation={validation}"
            )
            lines.append(f"  reason: {rewrite.reason}")
    if report.decision is not None:
        lines.extend(
            [
                "",
                render_heading("Decision"),
                f"  selected: {render_accent(report.decision.selected)}",
                f"  accepted: {report.decision.accepted}",
            ]
        )
        for reason in report.decision.reasons:
            lines.append(f"  reason: {reason}")
    if report.deployment is not None:
        lines.extend(["", *render_deployment_block(report.deployment, title="Board deployment")])
    if report.decision is not None:
        decision_status = "succeeded" if report.decision.accepted else "warning"
        lines.extend(
            [
                "",
                *render_notice(
                    "Run complete",
                    [f"Selected model  {report.decision.selected}"],
                    decision_status,
                ),
            ]
        )
    return "\n".join(lines)


def render_deployment_block(
    result: DeploymentResult, *, title: str = "STM32N6 deployment"
) -> list[str]:
    lines = [
        *render_key_values(
            title,
            [
                ("application", result.application),
                ("board", result.board),
                ("status", f"{render_status_icon(result.status)} {result.status}"),
                ("serial port", result.serial_port or "unknown"),
                ("boot mode", result.boot_mode or "unknown"),
            ],
        )
    ]
    if result.stages:
        lines.extend(["", render_heading("Stages")])
        for index, stage in enumerate(result.stages, 1):
            suffix = f" exit={stage.exit_code}" if stage.exit_code is not None else ""
            error = f" - {stage.first_error}" if stage.first_error else ""
            lines.append(
                render_progress_step(
                    index,
                    len(result.stages),
                    f"[{stage.status}] {stage.stage}",
                    stage.status,
                    f"{suffix}{error}".strip() or None,
                )
            )
    metric_items: list[tuple[str, object]] = [("inference observations", len(result.observations))]
    if result.observations:
        successful = sum(observation.success for observation in result.observations)
        latencies = [
            observation.latency_ms
            for observation in result.observations
            if observation.latency_ms is not None
        ]
        metric_items.append(("observations", f"{successful}/{len(result.observations)} succeeded"))
        if latencies:
            metric_items.append(
                (
                    "latency_ms",
                    f"min={min(latencies):.3f} "
                    f"mean={sum(latencies) / len(latencies):.3f} "
                    f"max={max(latencies):.3f}",
                )
            )
    lines.extend(["", *render_key_values("Measurements", metric_items)])
    if result.reason:
        lines.extend(["", *render_notice("Result", [result.reason], result.status)])
    return lines


def _format_tool(tool: ToolInfo | None) -> str:
    if tool is None:
        return "unknown"
    return f"{tool.name} {tool.version}".strip()


def _render_analysis(label: str, analysis: CompilationAnalysis) -> list[str]:
    lines = [
        render_heading(f"{label} pipeline"),
        *[
            render_progress_step(
                index,
                len(analysis.deployment_stages),
                f"[{stage.status}] {stage.stage}",
                stage.status,
                stage.first_error,
            )
            for index, stage in enumerate(analysis.deployment_stages, 1)
        ],
        "",
        *render_key_values(
            "Placement",
            [
                (
                    "epochs",
                    f"total={analysis.epochs.total_epochs} "
                    f"npu={analysis.epochs.accelerator_epochs} "
                    f"software={analysis.epochs.software_epochs}",
                ),
                ("partitions", analysis.graph.partition_count),
                ("accelerator/cpu transitions", analysis.graph.accelerator_cpu_transitions),
            ],
        ),
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
                *render_key_values(
                    "Memory",
                    [("deployable", analysis.resources.deployable)],
                ),
                "  compiler pools",
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


def render_status_icon(status: object) -> str:
    value = str(status)
    if value in {"available", "succeeded", "applied", "passed", "feasible"}:
        return _paint("OK" if _plain_banner_requested() else "✓", ARONA_OK)
    if value in {"warning", "partial", "skipped"}:
        return _paint("!", ARONA_WARN)
    if value in {"failed", "unavailable", "rejected", "rolled_back", "infeasible"}:
        return _paint("FAIL" if _plain_banner_requested() else "✗", ARONA_FAIL)
    return _paint("·", ARONA_BLUE)

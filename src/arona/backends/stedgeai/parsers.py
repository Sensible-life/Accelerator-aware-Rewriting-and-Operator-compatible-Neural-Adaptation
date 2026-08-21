"""Parsers for captured ST Edge AI compiler reports.

The parser accepts a compact ARONA fixture format and common human-readable log
phrases. Real vendor logs can be added incrementally without changing the normalized
contract returned to the rest of the pipeline.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from arona.contracts.v1 import (
    CompilerMemoryPool,
    DeploymentStage,
    DeploymentStageName,
    Diagnostic,
    EpochSummary,
    FallbackOperator,
    FeasibilityStatus,
    MemoryKind,
    QDQBoundary,
    Severity,
    StageStatus,
    StorageAllocation,
    StorageClass,
)


@dataclass(frozen=True)
class ParsedStEdgeAiLog:
    exit_code: int | None = None
    duration_ms: float | None = None
    epochs: EpochSummary = field(default_factory=EpochSummary)
    fallback_operators: tuple[FallbackOperator, ...] = ()
    qdq_boundaries: tuple[QDQBoundary, ...] = ()
    compiler_pools: tuple[CompilerMemoryPool, ...] = ()
    storage_allocations: tuple[StorageAllocation, ...] = ()
    activation_total_bytes: int | None = None
    activation_accelerator_bytes: int | None = None
    activation_cpu_bytes: int | None = None
    largest_contiguous_buffer_bytes: int | None = None
    deployment_stages: tuple[DeploymentStage, ...] = ()
    diagnostics: tuple[Diagnostic, ...] = ()
    raw_text: str = ""


@dataclass(frozen=True)
class _Core4MemoryUsage:
    name: str
    start_address: int
    used_bytes: int
    weight_bytes: int
    activation_bytes: int


def parse_stedgeai_log(path: Path) -> ParsedStEdgeAiLog:
    """Parse a captured compiler log into normalized pieces."""

    text = path.read_text(encoding="utf-8")
    return parse_stedgeai_text(text)


def parse_stedgeai_text(text: str) -> ParsedStEdgeAiLog:
    total_epochs = _first_int(text, r"(?:total epochs|epochs total)\s*[:=]\s*([0-9,]+)")
    npu_epochs = _first_int(text, r"(?:npu|accelerator|neural-art) epochs\s*[:=]\s*([0-9,]+)")
    software_epochs = _first_int(text, r"(?:software|cpu|cortex-m55) epochs\s*[:=]\s*([0-9,]+)")

    core4_total_epochs = _first_int(text, r"total number of epochs\s+([0-9,]+)")
    core4_hardware_epochs = _first_int(text, r">>\s*pure hardware \(HW or EC\) epochs\s+([0-9,]+)")
    core4_hybrid_epochs = _first_int(
        text, r">>\s*hybrid epochs \(using both software and hardware\)\s+([0-9,]+)"
    )
    core4_software_epochs = _first_int(text, r">>\s*pure software \(SW\) epochs\s+([0-9,]+)")
    total_epochs = total_epochs if total_epochs is not None else core4_total_epochs
    if npu_epochs is None and core4_hardware_epochs is not None:
        npu_epochs = core4_hardware_epochs + (core4_hybrid_epochs or 0)
    if software_epochs is None:
        software_epochs = core4_software_epochs

    fallback_operators = tuple(_parse_fallback_ops(text))
    qdq_boundaries = tuple(_parse_qdq_boundaries(text))
    core4_memory = _parse_core4_memory_usage(text)
    parsed_memory_pools = _parse_memory_pools(text)
    parsed_storage_allocations = _parse_storage_allocations(text)
    compiler_pools = tuple(parsed_memory_pools or _core4_compiler_pools(core4_memory))
    core4_weight_total_bytes = _first_int(text, r"weights \(ro\)\s*:\s*([0-9,]+)\s+B")
    storage_allocations = tuple(
        parsed_storage_allocations
        or _core4_storage_allocations(core4_memory, core4_weight_total_bytes)
    )
    deployment_stages = tuple(_parse_deployment_stages(text))
    diagnostics = tuple(_parse_diagnostics(text))

    activation_total_bytes = _first_int(text, r"activation total\s*[:=]\s*([0-9,]+)")
    if activation_total_bytes is None:
        activation_total_bytes = _first_int(text, r"activations \(rw\)\s*:\s*([0-9,]+)\s+B")
    accelerator_activation_bytes = _first_int(text, r"activation npu\s*[:=]\s*([0-9,]+)")
    if accelerator_activation_bytes is None and core4_memory:
        accelerator_activation_bytes = sum(
            usage.activation_bytes for usage in core4_memory if usage.name.lower().startswith("npu")
        )
    cpu_activation_bytes = _first_int(text, r"activation cpu\s*[:=]\s*([0-9,]+)")
    if cpu_activation_bytes is None and core4_memory:
        cpu_activation_bytes = sum(
            usage.activation_bytes
            for usage in core4_memory
            if usage.name.lower().startswith(("cpu", "flex"))
        )
    largest_contiguous_buffer_bytes = _first_int(
        text,
        r"largest contiguous (?:activation )?buffer\s*[:=]\s*([0-9,]+)",
    )
    if largest_contiguous_buffer_bytes is None and core4_memory:
        largest_contiguous_buffer_bytes = max(
            (usage.activation_bytes for usage in core4_memory),
            default=0,
        )

    return ParsedStEdgeAiLog(
        exit_code=_first_signed_int(text, r"exit code\s*[:=]\s*(-?[0-9]+)"),
        duration_ms=_first_float(text, r"duration ms\s*[:=]\s*([0-9]+(?:\.[0-9]+)?)"),
        epochs=EpochSummary(
            total_epochs=total_epochs,
            accelerator_epochs=npu_epochs,
            software_epochs=software_epochs,
        ),
        fallback_operators=fallback_operators,
        qdq_boundaries=qdq_boundaries,
        compiler_pools=compiler_pools,
        storage_allocations=storage_allocations,
        activation_total_bytes=activation_total_bytes,
        activation_accelerator_bytes=accelerator_activation_bytes,
        activation_cpu_bytes=cpu_activation_bytes,
        largest_contiguous_buffer_bytes=largest_contiguous_buffer_bytes,
        deployment_stages=deployment_stages,
        diagnostics=diagnostics,
        raw_text=text,
    )


def _parse_fallback_ops(text: str) -> list[FallbackOperator]:
    result: list[FallbackOperator] = []
    pattern = re.compile(
        r"fallback op\s*[:=]\s*(?P<op>[A-Za-z0-9_./-]+)"
        r"(?:\s+count\s*[:=]\s*(?P<count>[0-9,]+))?"
        r"(?:\s+reason\s*[:=]\s*(?P<reason>.+))?",
        re.IGNORECASE,
    )
    for match in pattern.finditer(text):
        result.append(
            FallbackOperator(
                op_type=match.group("op"),
                count=_clean_int(match.group("count")) if match.group("count") else 1,
                reason=_clean_optional(match.group("reason")),
            )
        )
    if result:
        return result

    software_epoch_pattern = re.compile(
        r"^\s*\|\s*epoch_[0-9]+\s*\|\s*SW\s*\|\s*(?P<op>[^|]*?)\s*\|\s*$",
        re.IGNORECASE | re.MULTILINE,
    )
    counts: dict[str, int] = {}
    for match in software_epoch_pattern.finditer(text):
        op_type = match.group("op").strip() or "SoftwareEpoch"
        counts[op_type] = counts.get(op_type, 0) + 1
    return [
        FallbackOperator(
            op_type=op_type,
            count=count,
            reason="pure software epoch in STEdgeAI Core report",
        )
        for op_type, count in sorted(counts.items())
    ]


def _parse_qdq_boundaries(text: str) -> list[QDQBoundary]:
    result: list[QDQBoundary] = []
    pattern = re.compile(
        r"qdq boundary\s*[:=]\s*(?P<tensor>[A-Za-z0-9_./:-]+)"
        r"(?:\s+shape\s*[:=]\s*(?P<shape>\[[^\]]*\]))?"
        r"(?:\s+dtype\s*[:=]\s*(?P<dtype>[A-Za-z0-9_]+))?"
        r"(?:\s+bytes\s*[:=]\s*(?P<bytes>[0-9,]+))?",
        re.IGNORECASE,
    )
    for match in pattern.finditer(text):
        result.append(
            QDQBoundary(
                tensor_name=match.group("tensor"),
                shape=_parse_shape(match.group("shape") or ""),
                data_type=_clean_optional(match.group("dtype")),
                estimated_transfer_bytes=(
                    _clean_int(match.group("bytes")) if match.group("bytes") else None
                ),
            )
        )
    return result


def _parse_memory_pools(text: str) -> list[CompilerMemoryPool]:
    result: list[CompilerMemoryPool] = []
    pattern = re.compile(
        r"memory pool\s*[:=]\s*(?P<name>[A-Za-z0-9_./:-]+)"
        r"\s+kind\s*[:=]\s*(?P<kind>[A-Za-z0-9_]+)"
        r"\s+start\s*[:=]\s*(?P<start>0x[0-9a-fA-F]+|[0-9,]+)"
        r"\s+size\s*[:=]\s*(?P<size>[0-9,]+)",
        re.IGNORECASE,
    )
    for match in pattern.finditer(text):
        result.append(
            CompilerMemoryPool(
                name=match.group("name"),
                kind=_memory_kind(match.group("kind")),
                start_address=_clean_int(match.group("start")),
                size_bytes=_clean_int(match.group("size")),
                feasible=FeasibilityStatus.UNKNOWN,
            )
        )
    return result


def _parse_core4_memory_usage(text: str) -> list[_Core4MemoryUsage]:
    pattern = re.compile(
        r"^\s*(?P<name>[A-Za-z][A-Za-z0-9_]*)\s+"
        r"\[(?P<start>0x[0-9a-fA-F]+)\s+-\s+0x[0-9a-fA-F]+\]:\s+"
        r"(?P<used>[0-9,.]+)\s*(?P<used_unit>[kKmM]?[iI]?[bB])\s+/\s+"
        r"[0-9,.]+\s*[kKmM]?[iI]?[bB].*?--\s+weights:\s+"
        r"(?P<weights>[0-9,.]+)\s*(?P<weights_unit>[kKmM]?[iI]?[bB]).*?"
        r"activations:\s+(?P<activations>[0-9,.]+)\s*"
        r"(?P<activations_unit>[kKmM]?[iI]?[bB])",
        re.IGNORECASE | re.MULTILINE,
    )
    used_range_pattern = re.compile(
        r"^\s*(?P<name>[A-Za-z][A-Za-z0-9_]*)\s+"
        r"\[0x[0-9a-fA-F]+\s+-\s+0x[0-9a-fA-F]+\]:\s+"
        r"(?P<used_start>0x[0-9a-fA-F]+)-(?P<used_end>0x[0-9a-fA-F]+)\s*$",
        re.IGNORECASE | re.MULTILINE,
    )
    exact_used_bytes = {
        match.group("name"): _clean_int(match.group("used_end"))
        - _clean_int(match.group("used_start"))
        for match in used_range_pattern.finditer(text)
    }
    result: list[_Core4MemoryUsage] = []
    for match in pattern.finditer(text):
        rounded_used_bytes = _parse_byte_size(match.group("used"), match.group("used_unit"))
        if rounded_used_bytes == 0:
            continue
        result.append(
            _Core4MemoryUsage(
                name=match.group("name"),
                start_address=_clean_int(match.group("start")),
                used_bytes=exact_used_bytes.get(match.group("name"), rounded_used_bytes),
                weight_bytes=_parse_byte_size(match.group("weights"), match.group("weights_unit")),
                activation_bytes=_parse_byte_size(
                    match.group("activations"), match.group("activations_unit")
                ),
            )
        )
    return result


def _core4_compiler_pools(
    memory_usage: list[_Core4MemoryUsage],
) -> list[CompilerMemoryPool]:
    return [
        CompilerMemoryPool(
            name=usage.name,
            kind=_memory_kind(usage.name),
            start_address=usage.start_address,
            size_bytes=usage.used_bytes,
            feasible=FeasibilityStatus.UNKNOWN,
        )
        for usage in memory_usage
    ]


def _core4_storage_allocations(
    memory_usage: list[_Core4MemoryUsage],
    exact_weight_total_bytes: int | None,
) -> list[StorageAllocation]:
    result: list[StorageAllocation] = []
    weight_usages = [usage for usage in memory_usage if usage.weight_bytes]
    for usage in memory_usage:
        if usage.weight_bytes:
            weight_bytes = (
                exact_weight_total_bytes
                if len(weight_usages) == 1 and exact_weight_total_bytes is not None
                else usage.weight_bytes
            )
            result.append(
                StorageAllocation(
                    storage_class=StorageClass.WEIGHT,
                    region_name=usage.name,
                    start_address=usage.start_address,
                    size_bytes=weight_bytes,
                    feasible=FeasibilityStatus.UNKNOWN,
                )
            )
        if usage.activation_bytes:
            result.append(
                StorageAllocation(
                    storage_class=StorageClass.ACTIVATION,
                    region_name=usage.name,
                    start_address=usage.start_address,
                    size_bytes=usage.activation_bytes,
                    feasible=FeasibilityStatus.UNKNOWN,
                )
            )
    return result


def _parse_storage_allocations(text: str) -> list[StorageAllocation]:
    result: list[StorageAllocation] = []
    pattern = re.compile(
        r"storage\s*[:=]\s*(?P<class>[A-Za-z0-9_]+)"
        r"\s+region\s*[:=]\s*(?P<region>[A-Za-z0-9_./:-]+)"
        r"(?:\s+start\s*[:=]\s*(?P<start>0x[0-9a-fA-F]+|[0-9,]+))?"
        r"\s+size\s*[:=]\s*(?P<size>[0-9,]+)"
        r"(?:\s+align(?:ment)?\s*[:=]\s*(?P<alignment>[0-9,]+))?",
        re.IGNORECASE,
    )
    for match in pattern.finditer(text):
        result.append(
            StorageAllocation(
                storage_class=_storage_class(match.group("class")),
                region_name=match.group("region"),
                start_address=(_clean_int(match.group("start")) if match.group("start") else None),
                size_bytes=_clean_int(match.group("size")),
                alignment=(
                    _clean_int(match.group("alignment")) if match.group("alignment") else None
                ),
                feasible=FeasibilityStatus.UNKNOWN,
            )
        )
    return result


def _parse_deployment_stages(text: str) -> list[DeploymentStage]:
    stages: dict[DeploymentStageName, DeploymentStage] = {}
    pattern = re.compile(
        r"stage\s*[:=]\s*(?P<stage>[a-z_]+)\s+status\s*[:=]\s*(?P<status>[a-z_]+)"
        r"(?:\s+exit\s*[:=]\s*(?P<exit>-?[0-9]+))?"
        r"(?:\s+error\s*[:=]\s*(?P<error>.+))?",
        re.IGNORECASE,
    )
    for match in pattern.finditer(text):
        stage_name = DeploymentStageName(match.group("stage").lower())
        stages[stage_name] = DeploymentStage(
            stage=stage_name,
            status=StageStatus(match.group("status").lower()),
            exit_code=int(match.group("exit")) if match.group("exit") else None,
            first_error=_clean_optional(match.group("error")),
        )

    return [
        stages.get(
            stage_name,
            DeploymentStage(stage=stage_name, status=StageStatus.SKIPPED),
        )
        for stage_name in DeploymentStageName
    ]


def _parse_diagnostics(text: str) -> list[Diagnostic]:
    diagnostics: list[Diagnostic] = []
    for line in text.splitlines():
        stripped = line.strip()
        lowered = stripped.lower()
        if lowered.startswith("warning:"):
            diagnostics.append(
                Diagnostic(
                    severity=Severity.WARNING,
                    source="stedgeai",
                    message=stripped.removeprefix("WARNING:").removeprefix("Warning:").strip(),
                )
            )
        elif lowered.startswith("error:") or lowered.startswith("internal error:"):
            diagnostics.append(
                Diagnostic(
                    severity=Severity.ERROR,
                    source="stedgeai",
                    message=(
                        stripped.removeprefix("INTERNAL ERROR:")
                        .removeprefix("Internal error:")
                        .removeprefix("ERROR:")
                        .removeprefix("Error:")
                        .strip()
                    ),
                )
            )
    return diagnostics


def _first_int(text: str, pattern: str) -> int | None:
    match = re.search(pattern, text, re.IGNORECASE)
    if not match:
        return None
    return _clean_int(match.group(1))


def _first_signed_int(text: str, pattern: str) -> int | None:
    match = re.search(pattern, text, re.IGNORECASE)
    return int(match.group(1)) if match else None


def _first_float(text: str, pattern: str) -> float | None:
    match = re.search(pattern, text, re.IGNORECASE)
    return float(match.group(1)) if match else None


def _clean_int(value: str) -> int:
    if value.lower().startswith("0x"):
        return int(value, 16)
    return int(value.replace(",", ""))


def _parse_byte_size(value: str, unit: str) -> int:
    normalized_unit = unit.lower()
    multiplier = 1
    if normalized_unit in {"kb", "kib"}:
        multiplier = 1024
    elif normalized_unit in {"mb", "mib"}:
        multiplier = 1024 * 1024
    return round(float(value.replace(",", "")) * multiplier)


def _clean_optional(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


def _parse_shape(value: str) -> list[int | str | None]:
    stripped = value.strip().strip("[]")
    if not stripped:
        return []
    shape: list[int | str | None] = []
    for item in stripped.split(","):
        item = item.strip()
        if item in {"?", "None", "none"}:
            shape.append(None)
        elif item.isdigit():
            shape.append(int(item))
        else:
            shape.append(item)
    return shape


def _memory_kind(value: str) -> MemoryKind:
    normalized = value.lower()
    aliases = {
        "sram": MemoryKind.INTERNAL_SRAM,
        "internal_sram": MemoryKind.INTERNAL_SRAM,
        "flash": MemoryKind.EXTERNAL_FLASH,
        "external_flash": MemoryKind.EXTERNAL_FLASH,
        "hyperram": MemoryKind.EXTERNAL_RAM,
        "psram": MemoryKind.EXTERNAL_RAM,
        "external_ram": MemoryKind.EXTERNAL_RAM,
        "tcm": MemoryKind.TCM,
    }
    if normalized.startswith(("npu", "cpu", "flex")):
        return MemoryKind.INTERNAL_SRAM
    if "flash" in normalized:
        return MemoryKind.EXTERNAL_FLASH
    if "ram" in normalized:
        return MemoryKind.EXTERNAL_RAM
    return aliases.get(normalized, MemoryKind.UNKNOWN)


def _storage_class(value: str) -> StorageClass:
    normalized = value.lower().replace(".", "").replace("-", "_")
    aliases = {
        "text": StorageClass.CODE,
        "code": StorageClass.CODE,
        "rodata": StorageClass.RODATA,
        "const": StorageClass.RODATA,
        "weight": StorageClass.WEIGHT,
        "weights": StorageClass.WEIGHT,
        "activation": StorageClass.ACTIVATION,
        "activations": StorageClass.ACTIVATION,
        "data": StorageClass.DATA_BSS,
        "bss": StorageClass.DATA_BSS,
        "data_bss": StorageClass.DATA_BSS,
        "heap": StorageClass.HEAP,
        "stack": StorageClass.STACK,
    }
    return aliases[normalized]

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


def parse_stedgeai_log(path: Path) -> ParsedStEdgeAiLog:
    """Parse a captured compiler log into normalized pieces."""

    text = path.read_text(encoding="utf-8")
    return parse_stedgeai_text(text)


def parse_stedgeai_text(text: str) -> ParsedStEdgeAiLog:
    total_epochs = _first_int(text, r"(?:total epochs|epochs total)\s*[:=]\s*([0-9,]+)")
    npu_epochs = _first_int(text, r"(?:npu|accelerator|neural-art) epochs\s*[:=]\s*([0-9,]+)")
    software_epochs = _first_int(text, r"(?:software|cpu|cortex-m55) epochs\s*[:=]\s*([0-9,]+)")

    fallback_operators = tuple(_parse_fallback_ops(text))
    qdq_boundaries = tuple(_parse_qdq_boundaries(text))
    compiler_pools = tuple(_parse_memory_pools(text))
    storage_allocations = tuple(_parse_storage_allocations(text))
    deployment_stages = tuple(_parse_deployment_stages(text))
    diagnostics = tuple(_parse_diagnostics(text))

    return ParsedStEdgeAiLog(
        epochs=EpochSummary(
            total_epochs=total_epochs,
            accelerator_epochs=npu_epochs,
            software_epochs=software_epochs,
        ),
        fallback_operators=fallback_operators,
        qdq_boundaries=qdq_boundaries,
        compiler_pools=compiler_pools,
        storage_allocations=storage_allocations,
        activation_total_bytes=_first_int(text, r"activation total\s*[:=]\s*([0-9,]+)"),
        activation_accelerator_bytes=_first_int(text, r"activation npu\s*[:=]\s*([0-9,]+)"),
        activation_cpu_bytes=_first_int(text, r"activation cpu\s*[:=]\s*([0-9,]+)"),
        largest_contiguous_buffer_bytes=_first_int(
            text,
            r"largest contiguous (?:activation )?buffer\s*[:=]\s*([0-9,]+)",
        ),
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
    return result


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
                start_address=(
                    _clean_int(match.group("start")) if match.group("start") else None
                ),
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
        elif lowered.startswith("error:"):
            diagnostics.append(
                Diagnostic(
                    severity=Severity.ERROR,
                    source="stedgeai",
                    message=stripped.removeprefix("ERROR:").removeprefix("Error:").strip(),
                )
            )
    return diagnostics


def _first_int(text: str, pattern: str) -> int | None:
    match = re.search(pattern, text, re.IGNORECASE)
    if not match:
        return None
    return _clean_int(match.group(1))


def _clean_int(value: str) -> int:
    if value.lower().startswith("0x"):
        return int(value, 16)
    return int(value.replace(",", ""))


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

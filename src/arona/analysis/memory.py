"""Memory resource feasibility checks."""

from arona.contracts.v1 import (
    CompilerMemoryPool,
    Diagnostic,
    FeasibilityStatus,
    MemoryResource,
    Severity,
)


def annotate_compiler_pools(
    compiler_pools: list[CompilerMemoryPool],
    board_regions: list[MemoryResource],
) -> list[CompilerMemoryPool]:
    """Mark compiler pools feasible only when fully covered by a real board region."""

    annotated: list[CompilerMemoryPool] = []
    for pool in compiler_pools:
        matched_region = _find_covering_region(pool, board_regions)
        diagnostics = list(pool.diagnostics)
        if matched_region is None:
            diagnostics.append(
                Diagnostic(
                    severity=Severity.ERROR,
                    source="memory.feasibility",
                    message=(
                        f"Compiler pool {pool.name} at 0x{pool.start_address:08x} "
                        f"({pool.size_bytes} bytes) is not covered by a board memory region."
                    ),
                    code="memory_pool_not_on_board",
                )
            )
            annotated.append(
                pool.model_copy(
                    update={
                        "mapped_region_name": None,
                        "feasible": FeasibilityStatus.INFEASIBLE,
                        "diagnostics": diagnostics,
                    }
                )
            )
            continue

        annotated.append(
            pool.model_copy(
                update={
                    "mapped_region_name": matched_region.name,
                    "feasible": FeasibilityStatus.FEASIBLE,
                    "diagnostics": diagnostics,
                }
            )
        )

    return annotated


def has_address_overlap(resources: list[MemoryResource]) -> bool:
    """Return true when any declared board regions overlap."""

    ordered = sorted(resources, key=lambda resource: resource.start_address)
    for previous, current in zip(ordered, ordered[1:], strict=False):
        previous_end = previous.start_address + previous.size_bytes
        if current.start_address < previous_end:
            return True
    return False


def _find_covering_region(
    pool: CompilerMemoryPool,
    regions: list[MemoryResource],
) -> MemoryResource | None:
    pool_end = pool.start_address + pool.size_bytes
    for region in regions:
        region_end = region.start_address + region.size_bytes
        if (
            region.exists_on_board
            and region.start_address <= pool.start_address
            and pool_end <= region_end
        ):
            return region
    return None

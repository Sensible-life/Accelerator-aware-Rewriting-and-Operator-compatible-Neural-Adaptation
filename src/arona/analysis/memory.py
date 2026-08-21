"""Memory resource feasibility checks."""

from arona.contracts.v1 import (
    CompilerMemoryPool,
    Diagnostic,
    FeasibilityStatus,
    MemoryKind,
    MemoryResource,
    Severity,
    StorageAllocation,
    StorageClass,
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


def annotate_storage_allocations(
    storage_allocations: list[StorageAllocation],
    compiler_pools: list[CompilerMemoryPool],
    board_regions: list[MemoryResource],
) -> list[StorageAllocation]:
    """Mark storage allocations feasible only when their target memory is valid."""

    annotated: list[StorageAllocation] = []
    regions_by_name = {region.name: region for region in board_regions}
    pools_by_name = {pool.name: pool for pool in compiler_pools}

    for allocation in storage_allocations:
        diagnostics = list(allocation.diagnostics)
        region = regions_by_name.get(allocation.region_name)
        pool = pools_by_name.get(allocation.region_name)

        if region is None and pool is not None:
            if pool.feasible == FeasibilityStatus.INFEASIBLE:
                diagnostics.append(
                    Diagnostic(
                        severity=Severity.ERROR,
                        source="memory.storage",
                        message=(
                            f"Storage class {allocation.storage_class} is assigned to "
                            f"compiler pool {pool.name}, which is not feasible on the board."
                        ),
                        code="storage_pool_not_feasible",
                    )
                )
                annotated.append(
                    allocation.model_copy(
                        update={
                            "feasible": FeasibilityStatus.INFEASIBLE,
                            "diagnostics": diagnostics,
                        }
                    )
                )
                continue
            region = regions_by_name.get(pool.mapped_region_name or "")

        if region is None:
            diagnostics.append(
                Diagnostic(
                    severity=Severity.ERROR,
                    source="memory.storage",
                    message=(
                        f"Storage class {allocation.storage_class} references unknown "
                        f"region or pool {allocation.region_name}."
                    ),
                    code="storage_region_unknown",
                )
            )
            annotated.append(
                allocation.model_copy(
                    update={
                        "feasible": FeasibilityStatus.INFEASIBLE,
                        "diagnostics": diagnostics,
                    }
                )
            )
            continue

        if not _allocation_fits_region(allocation, region):
            diagnostics.append(
                Diagnostic(
                    severity=Severity.ERROR,
                    source="memory.storage",
                    message=(
                        f"Storage class {allocation.storage_class} does not fit within "
                        f"board region {region.name}."
                    ),
                    code="storage_allocation_out_of_region",
                )
            )

        if not _storage_class_allowed(allocation.storage_class, region.kind):
            diagnostics.append(
                Diagnostic(
                    severity=Severity.ERROR,
                    source="memory.storage",
                    message=(
                        f"Storage class {allocation.storage_class} is not compatible with "
                        f"memory kind {region.kind} in region {region.name}."
                    ),
                    code="storage_class_incompatible_with_region",
                )
            )

        feasible = (
            FeasibilityStatus.INFEASIBLE if diagnostics else FeasibilityStatus.FEASIBLE
        )
        annotated.append(
            allocation.model_copy(update={"feasible": feasible, "diagnostics": diagnostics})
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


def _allocation_fits_region(allocation: StorageAllocation, region: MemoryResource) -> bool:
    if not region.exists_on_board:
        return False
    if allocation.start_address is None:
        return allocation.size_bytes <= region.size_bytes

    allocation_end = allocation.start_address + allocation.size_bytes
    region_end = region.start_address + region.size_bytes
    return region.start_address <= allocation.start_address and allocation_end <= region_end


def _storage_class_allowed(storage_class: StorageClass, memory_kind: MemoryKind) -> bool:
    allowed: dict[StorageClass, set[MemoryKind]] = {
        StorageClass.CODE: {
            MemoryKind.INTERNAL_SRAM,
            MemoryKind.EXTERNAL_FLASH,
            MemoryKind.TCM,
        },
        StorageClass.RODATA: {
            MemoryKind.INTERNAL_SRAM,
            MemoryKind.EXTERNAL_FLASH,
            MemoryKind.TCM,
        },
        StorageClass.WEIGHT: {
            MemoryKind.INTERNAL_SRAM,
            MemoryKind.EXTERNAL_FLASH,
            MemoryKind.EXTERNAL_RAM,
        },
        StorageClass.ACTIVATION: {
            MemoryKind.INTERNAL_SRAM,
            MemoryKind.EXTERNAL_RAM,
            MemoryKind.TCM,
        },
        StorageClass.DATA_BSS: {
            MemoryKind.INTERNAL_SRAM,
            MemoryKind.EXTERNAL_RAM,
            MemoryKind.TCM,
        },
        StorageClass.HEAP: {
            MemoryKind.INTERNAL_SRAM,
            MemoryKind.EXTERNAL_RAM,
            MemoryKind.TCM,
        },
        StorageClass.STACK: {
            MemoryKind.INTERNAL_SRAM,
            MemoryKind.TCM,
        },
    }
    return memory_kind in allowed[storage_class]

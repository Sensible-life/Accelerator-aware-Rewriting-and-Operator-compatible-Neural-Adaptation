"""Known board memory profiles for the ST Edge AI backend."""

from arona.contracts.v1 import MemoryKind, MemoryResource


def nucleo_n657x0_q_regions() -> list[MemoryResource]:
    """Return the conservative MVP board profile for NUCLEO-N657X0-Q.

    The profile intentionally does not include HyperRAM/PSRAM. If a local board setup
    adds external RAM, the probe result or backend configuration should add it with
    evidence rather than assuming it here.
    """

    return [
        MemoryResource(
            name="AXISRAM1",
            kind=MemoryKind.INTERNAL_SRAM,
            start_address=0x3400_0000,
            size_bytes=2 * 1024 * 1024,
            attributes=["rw", "activation"],
            exists_on_board=True,
            source="arona.stedgeai.nucleo_n657x0_q",
        ),
        MemoryResource(
            name="AXISRAM2",
            kind=MemoryKind.INTERNAL_SRAM,
            start_address=0x3420_0000,
            size_bytes=2 * 1024 * 1024,
            attributes=["rw", "activation", "data"],
            exists_on_board=True,
            source="arona.stedgeai.nucleo_n657x0_q",
        ),
        MemoryResource(
            name="XSPI1_FLASH",
            kind=MemoryKind.EXTERNAL_FLASH,
            start_address=0x7000_0000,
            size_bytes=64 * 1024 * 1024,
            attributes=["rx", "xip", "weight", "rodata"],
            exists_on_board=True,
            source="arona.stedgeai.nucleo_n657x0_q",
        ),
    ]

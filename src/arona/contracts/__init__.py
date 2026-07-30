"""Versioned data contracts shared by ARONA backends and UI."""

from arona.contracts.v1 import (
    CONTRACT_VERSION,
    DeviceDiscovery,
    OptimizeRequest,
    RunReport,
)

__all__ = [
    "CONTRACT_VERSION",
    "DeviceDiscovery",
    "OptimizeRequest",
    "RunReport",
]

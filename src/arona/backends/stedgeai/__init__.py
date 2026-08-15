"""ST Edge AI backend adapter."""

from typing import Any

__all__ = ["StEdgeAiAdapter"]


def __getattr__(name: str) -> Any:
    if name == "StEdgeAiAdapter":
        from arona.backends.stedgeai.adapter import StEdgeAiAdapter

        return StEdgeAiAdapter
    raise AttributeError(name)

"""Stable ARONA node IDs for ONNX graphs."""

import onnx


def stable_node_id(source_index: int) -> str:
    """Return the default stable ID for an ONNX node source index."""

    return f"node_{source_index:04d}"


def stable_node_ids(model: onnx.ModelProto) -> dict[int, str]:
    """Return a source-index keyed mapping of stable node IDs."""

    return {index: stable_node_id(index) for index, _node in enumerate(model.graph.node)}

"""Externalize a terminal ONNX ArgMax into explicit MCU post-processing."""

from __future__ import annotations

import copy
from pathlib import Path

import onnx
from onnx import AttributeProto, TensorProto, checker

from arona.contracts.v1 import (
    ArgMaxPostprocess,
    ArtifactKind,
    ArtifactRef,
    RewriteKind,
    RewriteRecord,
    RewriteStatus,
)
from arona.graph.base import RewriteOutcome
from arona.onnx_frontend.checksum import sha256_file
from arona.onnx_frontend.loader import OnnxLoadResult
from arona.onnx_frontend.node_id import stable_node_id


class TerminalArgMaxRule:
    """Remove one terminal ArgMax when its result is only a graph output."""

    rule_id = "terminal_argmax_externalization.v1"
    kind = RewriteKind.EXACT

    def apply(self, model: OnnxLoadResult, output_directory: Path) -> RewriteOutcome:
        rejection = _rejection_reason(model)
        if rejection is not None:
            return _rejected(rejection)

        graph = model.model.graph
        output_name = graph.output[0].name
        node_index, node = next(
            (index, candidate)
            for index, candidate in enumerate(graph.node)
            if output_name in candidate.output
        )
        node_id = stable_node_id(node_index)
        input_name = node.input[0]
        value_info = _find_value_info(model.inferred_model, input_name)
        if value_info is None:
            return _rejected(
                f"ArgMax input tensor metadata is unavailable: {input_name}",
                affected_node_ids=[node_id],
            )

        axis = _int_attribute(node, "axis", 0)
        keepdims = bool(_int_attribute(node, "keepdims", 1))
        select_last_index = bool(_int_attribute(node, "select_last_index", 0))
        rank = len(value_info.type.tensor_type.shape.dim)
        if rank == 0 or not -rank <= axis < rank:
            return _rejected(
                f"ArgMax axis {axis} is invalid for rank {rank}.",
                affected_node_ids=[node_id],
            )

        optimized = copy.deepcopy(model.model)
        del optimized.graph.node[node_index]
        del optimized.graph.output[:]
        optimized.graph.output.append(copy.deepcopy(value_info))
        checker.check_model(optimized)

        output_directory.mkdir(parents=True, exist_ok=True)
        optimized_model_path = output_directory / "optimized-model.onnx"
        postprocess_path = output_directory / "postprocess.json"
        onnx.save(optimized, optimized_model_path)

        postprocess = ArgMaxPostprocess(
            source_node_id=node_id,
            input_name=input_name,
            output_name=output_name,
            axis=axis,
            keepdims=keepdims,
            select_last_index=select_last_index,
        )
        postprocess_path.write_text(postprocess.model_dump_json(indent=2) + "\n", encoding="utf-8")

        artifact = ArtifactRef(
            kind=ArtifactKind.OPTIMIZED_MODEL,
            path=str(optimized_model_path),
            media_type="application/onnx",
            sha256=sha256_file(optimized_model_path),
            size_bytes=optimized_model_path.stat().st_size,
            description="ONNX model with terminal ArgMax externalized",
        )
        record = RewriteRecord(
            rewrite_id="terminal-argmax-1",
            rule_id=self.rule_id,
            kind=self.kind,
            status=RewriteStatus.APPLIED,
            affected_node_ids=[node_id],
            reason=(
                "Terminal ArgMax is the sole graph-output producer and has no graph consumers; "
                "it was moved to explicit MCU post-processing."
            ),
            candidate_model=artifact,
        )
        return RewriteOutcome(
            record=record,
            optimized_model_path=optimized_model_path,
            postprocess_path=postprocess_path,
            postprocess=postprocess,
        )


def _rejection_reason(model: OnnxLoadResult) -> str | None:
    graph = model.model.graph
    if len(graph.output) != 1:
        return "The MVP rule requires exactly one graph output."

    output_name = graph.output[0].name
    producers = [node for node in graph.node if output_name in node.output]
    if len(producers) != 1:
        return f"Graph output must have exactly one producer: {output_name}."

    node = producers[0]
    if node.op_type != "ArgMax" or node.domain not in {"", "ai.onnx"}:
        return "The sole graph output is not produced by a standard ONNX ArgMax."
    if len(node.input) != 1 or len(node.output) != 1:
        return "Terminal ArgMax must have exactly one input and one output."

    consumers = [candidate for candidate in graph.node if output_name in candidate.input]
    if consumers:
        return "ArgMax output is consumed by another graph node."

    output_type = graph.output[0].type.tensor_type.elem_type
    if output_type != TensorProto.INT64:
        return "ArgMax graph output must use the ONNX int64 output type."

    for attribute in node.attribute:
        if attribute.name not in {"axis", "keepdims", "select_last_index"}:
            return f"Unsupported ArgMax attribute: {attribute.name}."
        if attribute.type != AttributeProto.INT:
            return f"ArgMax attribute must be an integer: {attribute.name}."
    return None


def _find_value_info(model: onnx.ModelProto, tensor_name: str) -> onnx.ValueInfoProto | None:
    values = [*model.graph.input, *model.graph.value_info, *model.graph.output]
    return next((value for value in values if value.name == tensor_name), None)


def _int_attribute(node: onnx.NodeProto, name: str, default: int) -> int:
    return next((attribute.i for attribute in node.attribute if attribute.name == name), default)


def _rejected(reason: str, affected_node_ids: list[str] | None = None) -> RewriteOutcome:
    return RewriteOutcome(
        record=RewriteRecord(
            rewrite_id="terminal-argmax-1",
            rule_id=TerminalArgMaxRule.rule_id,
            kind=TerminalArgMaxRule.kind,
            status=RewriteStatus.REJECTED,
            affected_node_ids=affected_node_ids or [],
            reason=reason,
        )
    )

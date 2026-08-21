from pathlib import Path

import numpy as np
import onnx
from onnx import TensorProto, helper

from arona.contracts.v1 import ArgMaxPostprocess, RewriteStatus, ValidationStatus
from arona.graph import TerminalArgMaxRule
from arona.onnx_frontend.loader import load_onnx_model_info
from arona.validation.onnxruntime import _apply_argmax, validate_externalized_argmax


def test_terminal_argmax_is_externalized_without_mutating_source(tmp_path: Path) -> None:
    model_path = tmp_path / "baseline.onnx"
    _write_terminal_argmax_model(model_path, axis=1, keepdims=0)
    loaded = load_onnx_model_info(model_path)

    outcome = TerminalArgMaxRule().apply(loaded, tmp_path / "run")

    assert outcome.record.status == RewriteStatus.APPLIED
    assert outcome.optimized_model_path is not None
    assert outcome.postprocess_path is not None
    assert outcome.postprocess is not None
    assert outcome.postprocess.axis == 1
    assert outcome.postprocess.keepdims is False
    assert [node.op_type for node in loaded.model.graph.node] == ["Identity", "ArgMax"]
    optimized = onnx.load(outcome.optimized_model_path)
    onnx.checker.check_model(optimized)
    assert [node.op_type for node in optimized.graph.node] == ["Identity"]
    assert optimized.graph.output[0].name == "scores"


def test_argmax_with_graph_consumer_is_rejected(tmp_path: Path) -> None:
    model_path = tmp_path / "consumed.onnx"
    _write_consumed_argmax_model(model_path)

    outcome = TerminalArgMaxRule().apply(load_onnx_model_info(model_path), tmp_path / "run")

    assert outcome.record.status == RewriteStatus.REJECTED
    assert "consumed" in outcome.record.reason
    assert not (tmp_path / "run" / "optimized-model.onnx").exists()


def test_non_argmax_graph_output_is_rejected(tmp_path: Path) -> None:
    model_path = tmp_path / "identity.onnx"
    _write_identity_model(model_path)

    outcome = TerminalArgMaxRule().apply(load_onnx_model_info(model_path), tmp_path / "run")

    assert outcome.record.status == RewriteStatus.REJECTED
    assert "not produced" in outcome.record.reason


def test_invalid_axis_is_rejected(tmp_path: Path) -> None:
    model_path = tmp_path / "invalid-axis.onnx"
    _write_terminal_argmax_model(model_path, axis=2, keepdims=0)

    outcome = TerminalArgMaxRule().apply(load_onnx_model_info(model_path), tmp_path / "run")

    assert outcome.record.status == RewriteStatus.REJECTED
    assert "invalid for rank" in outcome.record.reason


def test_externalized_argmax_matches_for_ten_inputs(tmp_path: Path) -> None:
    model_path = tmp_path / "baseline.onnx"
    _write_terminal_argmax_model(model_path, axis=1, keepdims=1)
    outcome = TerminalArgMaxRule().apply(load_onnx_model_info(model_path), tmp_path / "run")
    assert outcome.optimized_model_path is not None
    assert outcome.postprocess is not None

    result = validate_externalized_argmax(
        model_path,
        outcome.optimized_model_path,
        outcome.postprocess,
        tmp_path / "run" / "validation.json",
        sample_count=10,
        seed=7,
    )

    assert result.status == ValidationStatus.PASSED
    assert result.sample_count == 10
    assert result.outputs[0].max_absolute_error == 0


def test_validation_reports_mismatch_for_wrong_axis(tmp_path: Path) -> None:
    model_path = tmp_path / "baseline.onnx"
    _write_terminal_argmax_model(model_path, axis=1, keepdims=0)
    outcome = TerminalArgMaxRule().apply(load_onnx_model_info(model_path), tmp_path / "run")
    assert outcome.optimized_model_path is not None
    assert outcome.postprocess is not None
    wrong_postprocess = outcome.postprocess.model_copy(update={"axis": 0})

    result = validate_externalized_argmax(
        model_path,
        outcome.optimized_model_path,
        wrong_postprocess,
        tmp_path / "run" / "validation.json",
        sample_count=2,
    )

    assert result.status == ValidationStatus.FAILED


def test_validation_rejects_non_finite_candidate_output(tmp_path: Path) -> None:
    model_path = tmp_path / "non-finite.onnx"
    _write_non_finite_argmax_model(model_path)
    outcome = TerminalArgMaxRule().apply(load_onnx_model_info(model_path), tmp_path / "run")
    assert outcome.optimized_model_path is not None
    assert outcome.postprocess is not None

    result = validate_externalized_argmax(
        model_path,
        outcome.optimized_model_path,
        outcome.postprocess,
        tmp_path / "run" / "validation.json",
        sample_count=1,
    )

    assert result.status == ValidationStatus.ERROR
    assert result.reason == "candidate output contains NaN or Inf"


def test_select_last_index_and_keepdims_are_preserved() -> None:
    postprocess = ArgMaxPostprocess(
        source_node_id="node_0001",
        input_name="scores",
        output_name="class_index",
        axis=1,
        keepdims=True,
        select_last_index=True,
    )

    result = _apply_argmax(np.array([[2.0, 4.0, 4.0]], dtype=np.float32), postprocess)

    assert result.tolist() == [[2]]
    assert result.dtype == np.int64


def _write_terminal_argmax_model(path: Path, *, axis: int, keepdims: int) -> None:
    input_info = helper.make_tensor_value_info("input", TensorProto.FLOAT, [1, 3])
    output_shape = [1, 1] if keepdims else [1]
    output_info = helper.make_tensor_value_info("class_index", TensorProto.INT64, output_shape)
    graph = helper.make_graph(
        nodes=[
            helper.make_node("Identity", ["input"], ["scores"], name="identity_0"),
            helper.make_node(
                "ArgMax",
                ["scores"],
                ["class_index"],
                name="argmax_0",
                axis=axis,
                keepdims=keepdims,
            ),
        ],
        name="terminal_argmax",
        inputs=[input_info],
        outputs=[output_info],
        value_info=[helper.make_tensor_value_info("scores", TensorProto.FLOAT, [1, 3])],
    )
    model = helper.make_model(graph, opset_imports=[helper.make_opsetid("", 18)])
    model.ir_version = 10
    onnx.save(model, path)


def _write_consumed_argmax_model(path: Path) -> None:
    input_info = helper.make_tensor_value_info("input", TensorProto.FLOAT, [1, 3])
    argmax_info = helper.make_tensor_value_info("class_index", TensorProto.INT64, [1])
    graph = helper.make_graph(
        nodes=[
            helper.make_node(
                "ArgMax", ["input"], ["class_index"], axis=1, keepdims=0, name="argmax_0"
            ),
            helper.make_node("Identity", ["class_index"], ["copied"], name="identity_0"),
        ],
        name="consumed_argmax",
        inputs=[input_info],
        outputs=[argmax_info],
        value_info=[helper.make_tensor_value_info("copied", TensorProto.INT64, [1])],
    )
    model = helper.make_model(graph, opset_imports=[helper.make_opsetid("", 18)])
    model.ir_version = 10
    onnx.save(model, path)


def _write_identity_model(path: Path) -> None:
    input_info = helper.make_tensor_value_info("input", TensorProto.FLOAT, [1, 3])
    output_info = helper.make_tensor_value_info("output", TensorProto.FLOAT, [1, 3])
    graph = helper.make_graph(
        [helper.make_node("Identity", ["input"], ["output"], name="identity_0")],
        "identity",
        [input_info],
        [output_info],
    )
    model = helper.make_model(graph, opset_imports=[helper.make_opsetid("", 18)])
    model.ir_version = 10
    onnx.save(model, path)


def _write_non_finite_argmax_model(path: Path) -> None:
    input_info = helper.make_tensor_value_info("input", TensorProto.FLOAT, [1, 3])
    output_info = helper.make_tensor_value_info("class_index", TensorProto.INT64, [1])
    zero = helper.make_tensor("zero_value", TensorProto.FLOAT, [1], [0.0])
    graph = helper.make_graph(
        nodes=[
            helper.make_node("Constant", [], ["zero"], value=zero, name="zero_0"),
            helper.make_node("Div", ["input", "zero"], ["scores"], name="divide_0"),
            helper.make_node(
                "ArgMax",
                ["scores"],
                ["class_index"],
                name="argmax_0",
                axis=1,
                keepdims=0,
            ),
        ],
        name="non_finite_argmax",
        inputs=[input_info],
        outputs=[output_info],
        value_info=[helper.make_tensor_value_info("scores", TensorProto.FLOAT, [1, 3])],
    )
    model = helper.make_model(graph, opset_imports=[helper.make_opsetid("", 18)])
    model.ir_version = 10
    onnx.save(model, path)

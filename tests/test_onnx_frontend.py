from pathlib import Path

import onnx
import pytest
from onnx import TensorProto, helper
from onnx.checker import ValidationError

from arona.onnx_frontend.loader import load_onnx_model_info
from arona.onnx_frontend.node_id import stable_node_ids


def test_valid_onnx_is_loaded_checked_and_summarized(tmp_path: Path) -> None:
    model_path = tmp_path / "valid.onnx"
    _write_identity_model(model_path)

    result = load_onnx_model_info(model_path)

    assert result.info.node_count == 1
    assert result.info.inputs[0].shape == [1, 3]
    assert result.info.outputs[0].shape == [1, 3]
    assert stable_node_ids(result.model) == {0: "node_0000"}


def test_invalid_onnx_is_rejected(tmp_path: Path) -> None:
    model_path = tmp_path / "invalid.onnx"
    graph = helper.make_graph(
        nodes=[helper.make_node("Identity", ["missing"], ["output"])],
        name="invalid",
        inputs=[],
        outputs=[
            helper.make_tensor_value_info("output", TensorProto.FLOAT, [1, 3]),
        ],
    )
    onnx.save(helper.make_model(graph), model_path)

    with pytest.raises(ValidationError):
        load_onnx_model_info(model_path)


def _write_identity_model(path: Path) -> None:
    input_info = helper.make_tensor_value_info("input", TensorProto.FLOAT, [1, 3])
    output_info = helper.make_tensor_value_info("output", TensorProto.FLOAT, [1, 3])
    graph = helper.make_graph(
        nodes=[helper.make_node("Identity", ["input"], ["output"], name="identity_0")],
        name="identity",
        inputs=[input_info],
        outputs=[output_info],
    )
    model = helper.make_model(graph, opset_imports=[helper.make_opsetid("", 18)])
    onnx.save(model, path)

from pathlib import Path

import onnx
from onnx import TensorProto, helper

from arona.backends.stedgeai import StEdgeAiAdapter
from arona.backends.stedgeai.parsers import parse_stedgeai_log
from arona.onnx_frontend.loader import load_onnx_model_info

ROOT = Path(__file__).parents[1]
FIXTURES = ROOT / "tests/fixtures/backends/stedgeai"


def test_conmamba_fallback_epoch_and_memory_fixture() -> None:
    parsed = parse_stedgeai_log(FIXTURES / "conmamba_fallback/compiler.log")

    assert parsed.epochs.total_epochs == 2072
    assert parsed.epochs.software_epochs == 1530
    assert parsed.largest_contiguous_buffer_bytes == 827392
    assert any(pool.name == "HYPERRAM_ACTIVATION" for pool in parsed.compiler_pools)


def test_missing_hyperram_is_deployability_failure_not_operator_failure(tmp_path: Path) -> None:
    model_path = tmp_path / "model.onnx"
    _write_three_node_model(model_path)
    model = load_onnx_model_info(model_path)
    adapter = StEdgeAiAdapter()
    probe = adapter.probe()

    analysis = adapter.parse(
        compiler_log=FIXTURES / "conmamba_fallback/compiler.log",
        model=model,
        target=probe.target,
    )

    assert analysis.resources is not None
    assert analysis.resources.deployable == "infeasible"
    assert analysis.graph.unsupported_nodes == 0
    assert any(
        diagnostic.code == "memory_pool_not_on_board"
        for diagnostic in analysis.resources.diagnostics
    )


def test_xip_fixture_maps_to_real_board_regions(tmp_path: Path) -> None:
    model_path = tmp_path / "model.onnx"
    _write_three_node_model(model_path)
    model = load_onnx_model_info(model_path)
    adapter = StEdgeAiAdapter()
    probe = adapter.probe()

    analysis = adapter.parse(
        compiler_log=FIXTURES / "conmamba_xip_101/compiler.log",
        model=model,
        target=probe.target,
    )

    assert analysis.resources is not None
    assert analysis.resources.deployable == "feasible"
    assert analysis.epochs.software_epochs == 1200


def _write_three_node_model(path: Path) -> None:
    input_info = helper.make_tensor_value_info("input", TensorProto.FLOAT, [1, 3])
    output_info = helper.make_tensor_value_info("output", TensorProto.FLOAT, [1, 3])
    nodes = [
        helper.make_node("Identity", ["input"], ["a"], name="identity_0"),
        helper.make_node("Relu", ["a"], ["b"], name="relu_0"),
        helper.make_node("Identity", ["b"], ["output"], name="identity_1"),
    ]
    graph = helper.make_graph(nodes=nodes, name="tiny", inputs=[input_info], outputs=[output_info])
    model = helper.make_model(graph, opset_imports=[helper.make_opsetid("", 18)])
    onnx.save(model, path)

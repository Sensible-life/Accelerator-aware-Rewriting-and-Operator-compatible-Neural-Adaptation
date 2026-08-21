import json
from pathlib import Path

import onnx
from onnx import TensorProto, helper

from arona.backends.stedgeai import StEdgeAiAdapter
from arona.backends.stedgeai.parsers import parse_stedgeai_log
from arona.contracts.v1 import CompilationAnalysis
from arona.onnx_frontend.loader import load_onnx_model_info

ROOT = Path(__file__).parents[1]
FIXTURES = ROOT / "tests/fixtures/backends/stedgeai"


def test_conmamba_fallback_epoch_and_memory_fixture() -> None:
    parsed = parse_stedgeai_log(FIXTURES / "conmamba_fallback/compiler.log")
    expected = _expected("conmamba_fallback")

    assert parsed.epochs.total_epochs == expected["total_epochs"]
    assert parsed.epochs.software_epochs == expected["software_epochs"]
    assert parsed.largest_contiguous_buffer_bytes == expected[
        "largest_contiguous_buffer_bytes"
    ]
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
    expected = _expected("conmamba_fallback")

    assert analysis.resources is not None
    assert analysis.resources.deployable == expected["deployable"]
    assert analysis.graph.unsupported_nodes == 0
    assert _pool_feasibility(analysis) == expected["compiler_pools"]
    assert _storage_feasibility(analysis) == expected["storage_allocations"]
    assert _diagnostic_codes(analysis) == set(expected["diagnostic_codes"])


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
    expected = _expected("conmamba_xip_101")

    assert analysis.resources is not None
    assert analysis.resources.deployable == expected["deployable"]
    assert analysis.epochs.software_epochs == expected["software_epochs"]
    assert _pool_feasibility(analysis) == expected["compiler_pools"]
    assert _storage_feasibility(analysis) == expected["storage_allocations"]
    assert _diagnostic_codes(analysis) == set(expected["diagnostic_codes"])


def _expected(case_id: str) -> dict[str, object]:
    path = FIXTURES / case_id / "expected-analysis.json"
    return json.loads(path.read_text(encoding="utf-8"))


def _pool_feasibility(analysis: CompilationAnalysis) -> dict[str, str]:
    resources = analysis.resources
    assert resources is not None
    return {pool.name: str(pool.feasible) for pool in resources.compiler_pools}


def _storage_feasibility(analysis: CompilationAnalysis) -> dict[str, str]:
    resources = analysis.resources
    assert resources is not None
    return {
        str(allocation.storage_class): str(allocation.feasible)
        for allocation in resources.storage_allocations
    }


def _diagnostic_codes(analysis: CompilationAnalysis) -> set[str]:
    resources = analysis.resources
    assert resources is not None
    return {
        diagnostic.code
        for diagnostic in resources.diagnostics
        if diagnostic.code is not None
    }


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

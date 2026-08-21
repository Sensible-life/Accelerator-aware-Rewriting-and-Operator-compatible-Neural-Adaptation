"""Load, validate, and summarize ONNX models."""

from dataclasses import dataclass
from pathlib import Path

import onnx
from onnx import TensorProto, checker, shape_inference

from arona.contracts.v1 import Diagnostic, ModelInfo, Severity, TensorSpec
from arona.onnx_frontend.checksum import sha256_file


@dataclass(frozen=True)
class OnnxLoadResult:
    model: onnx.ModelProto
    inferred_model: onnx.ModelProto
    info: ModelInfo
    diagnostics: tuple[Diagnostic, ...]


def load_onnx_model_info(path: Path) -> OnnxLoadResult:
    """Load an ONNX model, run checker and shape inference, and return contract data."""

    model_path = path.resolve()
    model = onnx.load(model_path)
    diagnostics: list[Diagnostic] = []

    try:
        checker.check_model(model)
    except checker.ValidationError as error:
        diagnostics.append(
            Diagnostic(
                severity=Severity.ERROR,
                source="onnx.checker",
                message=str(error),
                code="onnx_checker_failed",
            )
        )
        raise

    try:
        inferred_model = shape_inference.infer_shapes(model)
    except Exception as error:  # pragma: no cover - ONNX raises several concrete types.
        diagnostics.append(
            Diagnostic(
                severity=Severity.WARNING,
                source="onnx.shape_inference",
                message=str(error),
                code="shape_inference_failed",
            )
        )
        inferred_model = model

    info = ModelInfo(
        path=str(model_path),
        sha256=sha256_file(model_path),
        size_bytes=model_path.stat().st_size,
        ir_version=model.ir_version,
        opset_imports={opset.domain: opset.version for opset in model.opset_import},
        node_count=len(model.graph.node),
        inputs=[_tensor_spec(value) for value in inferred_model.graph.input],
        outputs=[_tensor_spec(value) for value in inferred_model.graph.output],
    )
    return OnnxLoadResult(
        model=model,
        inferred_model=inferred_model,
        info=info,
        diagnostics=tuple(diagnostics),
    )


def _tensor_spec(value: onnx.ValueInfoProto) -> TensorSpec:
    tensor_type = value.type.tensor_type
    shape: list[int | str | None] = []
    for dim in tensor_type.shape.dim:
        if dim.HasField("dim_value"):
            shape.append(dim.dim_value)
        elif dim.HasField("dim_param"):
            shape.append(dim.dim_param)
        else:
            shape.append(None)

    return TensorSpec(
        name=value.name,
        data_type=_data_type_name(tensor_type.elem_type),
        shape=shape,
        layout=_guess_layout(shape),
    )


def _data_type_name(elem_type: int) -> str:
    try:
        return str(TensorProto.DataType.Name(elem_type)).lower()
    except ValueError:
        return f"unknown({elem_type})"


def _guess_layout(shape: list[int | str | None]) -> str | None:
    if len(shape) == 4:
        return "NCHW"
    if len(shape) == 2:
        return "NC"
    return None

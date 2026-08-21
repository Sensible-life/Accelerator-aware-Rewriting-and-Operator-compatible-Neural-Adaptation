"""Create a baseline ONNX variant with a terminal ArgMax for the MVP rewrite demo."""

from __future__ import annotations

import argparse
import copy
from pathlib import Path

import onnx
from onnx import TensorProto, checker, helper


def create_variant(source: Path, destination: Path, axis: int = -1) -> None:
    """Append one terminal ArgMax while retaining the source tensor metadata."""

    model = onnx.load(source)
    checker.check_model(model)
    if len(model.graph.output) != 1:
        raise ValueError("the MVP fixture generator requires exactly one graph output")

    source_output = copy.deepcopy(model.graph.output[0])
    rank = len(source_output.type.tensor_type.shape.dim)
    if rank == 0 or not -rank <= axis < rank:
        raise ValueError(f"axis {axis} is invalid for output rank {rank}")

    output_name = "arona_class_index"
    existing_names = {
        name for node in model.graph.node for name in [*node.input, *node.output] if name
    }
    if output_name in existing_names:
        raise ValueError(f"generated output name already exists: {output_name}")

    model.graph.value_info.append(source_output)
    model.graph.node.append(
        helper.make_node(
            "ArgMax",
            [source_output.name],
            [output_name],
            name="arona_terminal_argmax",
            axis=axis,
            keepdims=0,
            select_last_index=0,
        )
    )

    normalized_axis = axis if axis >= 0 else rank + axis
    output_shape = [
        dimension.dim_value
        if dimension.HasField("dim_value")
        else dimension.dim_param
        if dimension.HasField("dim_param")
        else None
        for index, dimension in enumerate(source_output.type.tensor_type.shape.dim)
        if index != normalized_axis
    ]
    del model.graph.output[:]
    model.graph.output.append(
        helper.make_tensor_value_info(output_name, TensorProto.INT64, output_shape)
    )
    checker.check_model(model)
    destination.parent.mkdir(parents=True, exist_ok=True)
    onnx.save(model, destination)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path, help="Source ONNX model with one tensor output")
    parser.add_argument("destination", type=Path, help="Generated terminal-ArgMax ONNX path")
    parser.add_argument("--axis", type=int, default=-1, help="ArgMax axis (default: -1)")
    arguments = parser.parse_args()
    create_variant(arguments.source, arguments.destination, arguments.axis)
    print(arguments.destination)


if __name__ == "__main__":
    main()

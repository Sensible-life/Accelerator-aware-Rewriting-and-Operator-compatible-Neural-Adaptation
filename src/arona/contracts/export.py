"""JSON Schema export utilities."""

import json
from pathlib import Path

from pydantic import BaseModel

from arona.contracts.v1 import (
    ArgMaxPostprocess,
    DeviceDiscovery,
    DeviceProbe,
    OptimizeRequest,
    RunReport,
)

SCHEMA_MODELS: dict[str, type[BaseModel]] = {
    "device-discovery.schema.json": DeviceDiscovery,
    "device-probe.schema.json": DeviceProbe,
    "optimize-request.schema.json": OptimizeRequest,
    "postprocess.schema.json": ArgMaxPostprocess,
    "run-report.schema.json": RunReport,
}
SCHEMA_BASE_URI = "https://arona.dev/schemas/v0.1.0"


def export_json_schemas(output_directory: Path) -> list[Path]:
    """Write deterministic JSON Schema documents and return their paths."""
    output_directory.mkdir(parents=True, exist_ok=True)
    written_files: list[Path] = []

    for filename, model in SCHEMA_MODELS.items():
        path = output_directory / filename
        schema = model.model_json_schema(mode="serialization")
        schema["$schema"] = "https://json-schema.org/draft/2020-12/schema"
        schema["$id"] = f"{SCHEMA_BASE_URI}/{filename}"
        path.write_text(
            json.dumps(schema, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        written_files.append(path)

    return written_files

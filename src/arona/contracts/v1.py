"""Draft v0.1.0 contract shared by accelerator backends and the local UI.

Pydantic models in this module are the source of truth. Committed JSON Schema files
are generated from these models with ``arona schema export``.
"""

from datetime import datetime
from enum import StrEnum
from typing import Annotated, Final, Literal

from pydantic import BaseModel, ConfigDict, Field

CONTRACT_VERSION: Final = "0.1.0"
ContractVersion = Literal["0.1.0"]
NonNegativeInt = Annotated[int, Field(ge=0)]
NonNegativeFloat = Annotated[float, Field(ge=0)]
Ratio = Annotated[float, Field(ge=0, le=1)]
Sha256 = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
NonEmptyString = Annotated[str, Field(min_length=1)]
JsonScalar = str | int | float | bool | None


class ContractModel(BaseModel):
    """Base class that rejects fields unknown to the selected contract version."""

    model_config = ConfigDict(extra="forbid", validate_assignment=True)


class ConnectionType(StrEnum):
    LOCAL = "local"
    USB = "usb"
    SERIAL = "serial"
    NETWORK = "network"
    SIMULATOR = "simulator"


class Availability(StrEnum):
    AVAILABLE = "available"
    PARTIAL = "partial"
    UNAVAILABLE = "unavailable"


class RunStatus(StrEnum):
    QUEUED = "queued"
    DISCOVERING = "discovering"
    ANALYZING = "analyzing"
    OPTIMIZING = "optimizing"
    VALIDATING = "validating"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class CompilationStatus(StrEnum):
    SUCCEEDED = "succeeded"
    PARTIAL = "partial"
    FAILED = "failed"


class Placement(StrEnum):
    ACCELERATOR = "accelerator"
    CPU = "cpu"
    MIXED = "mixed"
    UNKNOWN = "unknown"


class SupportStatus(StrEnum):
    NATIVE = "native"
    CONSTRAINED = "constrained"
    FALLBACK = "fallback"
    UNSUPPORTED = "unsupported"
    UNKNOWN = "unknown"


class RewriteKind(StrEnum):
    EXACT = "exact"
    NEURAL = "neural"


class RewriteStatus(StrEnum):
    PROPOSED = "proposed"
    APPLIED = "applied"
    REJECTED = "rejected"
    ROLLED_BACK = "rolled_back"


class ValidationStatus(StrEnum):
    PASSED = "passed"
    FAILED = "failed"
    SKIPPED = "skipped"
    ERROR = "error"


class Severity(StrEnum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


class ArtifactKind(StrEnum):
    INPUT_MODEL = "input_model"
    OPTIMIZED_MODEL = "optimized_model"
    DEPLOYABLE = "deployable"
    COMPILER_LOG = "compiler_log"
    ANALYSIS = "analysis"
    VALIDATION = "validation"
    REWRITE_HISTORY = "rewrite_history"
    REPORT = "report"
    OTHER = "other"


class HostEnvironment(ContractModel):
    os: NonEmptyString
    architecture: NonEmptyString
    python_version: NonEmptyString
    hostname: str | None = None


class ToolInfo(ContractModel):
    name: NonEmptyString
    version: NonEmptyString
    executable: str | None = None
    metadata: dict[str, JsonScalar] = Field(default_factory=dict)


class ToolchainInfo(ContractModel):
    sdk: ToolInfo | None = None
    compiler: ToolInfo | None = None
    runtime: ToolInfo | None = None
    debugger: ToolInfo | None = None


class DeviceInfo(ContractModel):
    device_id: NonEmptyString
    vendor: NonEmptyString
    model: NonEmptyString
    accelerator: str | None = None
    connection: ConnectionType
    address: str | None = None
    firmware_version: str | None = None
    metadata: dict[str, JsonScalar] = Field(default_factory=dict)


class BackendCapabilities(ContractModel):
    input_formats: list[NonEmptyString] = Field(default_factory=lambda: ["onnx"])
    supports_compile: bool = True
    supports_node_placement: bool = False
    supports_cpu_fallback: bool = False
    supports_target_validation: bool = False
    supports_profiling: bool = False


class BackendTarget(ContractModel):
    target_id: NonEmptyString
    backend_name: NonEmptyString
    backend_version: NonEmptyString
    availability: Availability
    device: DeviceInfo | None = None
    toolchain: ToolchainInfo = Field(default_factory=ToolchainInfo)
    capabilities: BackendCapabilities = Field(default_factory=BackendCapabilities)
    issues: list[str] = Field(default_factory=list)


class DeviceDiscovery(ContractModel):
    """Result returned by backend discovery and consumed by target selection UI."""

    schema_version: ContractVersion = CONTRACT_VERSION
    generated_at: datetime
    host: HostEnvironment
    targets: list[BackendTarget] = Field(default_factory=list)


class InputModelReference(ContractModel):
    path: NonEmptyString
    sha256: Sha256 | None = None


class ValidationConfig(ContractModel):
    input_paths: list[NonEmptyString] = Field(default_factory=list)
    random_samples: NonNegativeInt = 0
    absolute_tolerance: NonNegativeFloat = 1e-5
    relative_tolerance: NonNegativeFloat = 1e-4


class OptimizationConfig(ContractModel):
    enable_exact_rewrites: bool = True
    enable_neural_adaptation: bool = False
    max_iterations: Annotated[int, Field(ge=1)] = 10
    require_measured_improvement: bool = True


class OptimizeRequest(ContractModel):
    """Request submitted by the UI or CLI to the optimization pipeline."""

    schema_version: ContractVersion = CONTRACT_VERSION
    model: InputModelReference
    target_id: str | None = None
    output_directory: NonEmptyString = "outputs"
    validation: ValidationConfig = Field(default_factory=ValidationConfig)
    optimization: OptimizationConfig = Field(default_factory=OptimizationConfig)


class TensorSpec(ContractModel):
    name: NonEmptyString
    data_type: NonEmptyString
    shape: list[int | str | None]
    layout: str | None = None


class ModelInfo(ContractModel):
    path: NonEmptyString
    sha256: Sha256
    size_bytes: NonNegativeInt
    ir_version: NonNegativeInt
    opset_imports: dict[str, NonNegativeInt]
    node_count: NonNegativeInt
    inputs: list[TensorSpec]
    outputs: list[TensorSpec]


class ArtifactRef(ContractModel):
    kind: ArtifactKind
    path: NonEmptyString
    media_type: str | None = None
    sha256: Sha256 | None = None
    size_bytes: NonNegativeInt | None = None
    description: str | None = None


class Diagnostic(ContractModel):
    severity: Severity
    source: NonEmptyString
    message: NonEmptyString
    code: str | None = None
    node_id: str | None = None


class NodeAnalysis(ContractModel):
    """Mapping between a stable ARONA node ID and a compiler placement decision."""

    node_id: NonEmptyString
    source_index: NonNegativeInt
    onnx_name: str | None = None
    op_type: NonEmptyString
    domain: str = ""
    support_status: SupportStatus
    placement: Placement
    backend_operator: str | None = None
    partition_id: str | None = None
    reasons: list[str] = Field(default_factory=list)


class TensorBoundary(ContractModel):
    tensor_name: NonEmptyString
    source_partition_id: str | None = None
    destination_partition_id: str | None = None
    source_placement: Placement
    destination_placement: Placement
    estimated_transfer_bytes: NonNegativeInt | None = None


class PartitionAnalysis(ContractModel):
    partition_id: NonEmptyString
    placement: Placement
    node_ids: list[NonEmptyString]
    boundaries: list[TensorBoundary] = Field(default_factory=list)


class GraphSummary(ContractModel):
    total_nodes: NonNegativeInt
    accelerator_nodes: NonNegativeInt
    cpu_nodes: NonNegativeInt
    unsupported_nodes: NonNegativeInt
    unknown_nodes: NonNegativeInt = 0
    accelerator_node_ratio: Ratio
    partition_count: NonNegativeInt
    accelerator_cpu_transitions: NonNegativeInt
    estimated_boundary_transfer_bytes: NonNegativeInt | None = None


class PerformanceMetrics(ContractModel):
    latency_mean_ms: NonNegativeFloat | None = None
    latency_p50_ms: NonNegativeFloat | None = None
    latency_p95_ms: NonNegativeFloat | None = None
    sample_count: NonNegativeInt | None = None
    peak_memory_bytes: NonNegativeInt | None = None
    source: Literal["compiler_estimate", "host_measurement", "target_measurement"] | None = None


class CompilerInvocation(ContractModel):
    command: list[NonEmptyString]
    working_directory: NonEmptyString
    exit_code: int | None = None
    duration_ms: NonNegativeFloat | None = None


class CompilationAnalysis(ContractModel):
    analysis_id: NonEmptyString
    status: CompilationStatus
    model_sha256: Sha256
    compiler: ToolInfo
    invocation: CompilerInvocation
    graph: GraphSummary
    nodes: list[NodeAnalysis] = Field(default_factory=list)
    partitions: list[PartitionAnalysis] = Field(default_factory=list)
    performance: PerformanceMetrics | None = None
    artifacts: list[ArtifactRef] = Field(default_factory=list)
    diagnostics: list[Diagnostic] = Field(default_factory=list)


class OutputError(ContractModel):
    output_name: NonEmptyString
    max_absolute_error: NonNegativeFloat
    mean_absolute_error: NonNegativeFloat
    max_relative_error: NonNegativeFloat | None = None
    cosine_similarity: Annotated[float, Field(ge=-1, le=1)] | None = None


class ValidationResult(ContractModel):
    status: ValidationStatus
    reference_runtime: NonEmptyString
    candidate_runtime: NonEmptyString
    sample_count: NonNegativeInt
    absolute_tolerance: NonNegativeFloat
    relative_tolerance: NonNegativeFloat
    outputs: list[OutputError] = Field(default_factory=list)
    reason: str | None = None
    artifact: ArtifactRef | None = None


class RewriteRecord(ContractModel):
    rewrite_id: NonEmptyString
    rule_id: NonEmptyString
    kind: RewriteKind
    status: RewriteStatus
    affected_node_ids: list[NonEmptyString]
    reason: NonEmptyString
    candidate_model: ArtifactRef | None = None
    validation: ValidationResult | None = None
    candidate_analysis_id: str | None = None


class OptimizationDecision(ContractModel):
    selected: Literal["baseline", "optimized"]
    accepted: bool
    reasons: list[NonEmptyString]
    accelerator_node_ratio_delta: float | None = None
    accelerator_cpu_transitions_delta: int | None = None
    latency_mean_delta_ms: float | None = None


class RunReport(ContractModel):
    """Canonical state/result document rendered by the UI and report generator."""

    schema_version: ContractVersion = CONTRACT_VERSION
    run_id: NonEmptyString
    status: RunStatus
    created_at: datetime
    updated_at: datetime
    target: BackendTarget
    model: ModelInfo
    baseline: CompilationAnalysis | None = None
    optimized: CompilationAnalysis | None = None
    rewrites: list[RewriteRecord] = Field(default_factory=list)
    decision: OptimizationDecision | None = None
    artifacts: list[ArtifactRef] = Field(default_factory=list)
    diagnostics: list[Diagnostic] = Field(default_factory=list)

"""Command-line entry point for ARONA."""

import os
import sys
from pathlib import Path
from typing import Annotated

import typer

from arona import __version__
from arona.contracts.export import export_json_schemas
from arona.contracts.v1 import DeploymentApplication, DeploymentResult, RunReport, StageStatus
from arona.deployment import (
    FirmwareImage,
    NucleoDeploymentConfig,
    Stm32N6Deployer,
    TelemetryInstrumentationError,
    configure_mvp_application,
    instrument_fixed_input_smoke,
    instrument_uart_telemetry,
    sync_stedgeai_runtime,
)
from arona.deployment.stm32n6 import (
    resolve_external_loader,
    resolve_gcc_directory,
    resolve_make,
    resolve_objcopy,
    resolve_programmer,
    resolve_signing_tool,
)
from arona.pipeline.analyze import analyze_model, discover_stedgeai
from arona.pipeline.optimize import optimize_model
from arona.reporting.markdown import render_markdown_report
from arona.reporting.terminal import (
    render_banner,
    render_deployment_block,
    render_discovery,
    render_run_report,
)

# denote arona as an app
app = typer.Typer(
    name="arona",
    help="Optimize ONNX models for detected edge accelerators.",
    no_args_is_help=True,
)

# create schema subcommand(ex: arona schema export)
schema_app = typer.Typer(help="Inspect and export backend/pipeline/CLI contracts.")
app.add_typer(schema_app, name="schema")
deployment_app = typer.Typer(help="Build, program, and validate STM32N6 deployments.")
app.add_typer(deployment_app, name="deployment")

DEFAULT_IMAGE_CLASSIFICATION_APPLICATION = Path(
    "outputs/vendor/STM32N6-GettingStarted-ImageClassification/Application/NUCLEO-N657X0-Q"
)
DEFAULT_IMAGE_CLASSIFICATION_MODEL_SUPPORT = Path(
    "outputs/vendor/STM32N6-GettingStarted-ImageClassification/Model"
)
DEFAULT_IMAGE_CLASSIFICATION_FSBL = Path(
    "outputs/vendor/STM32N6-GettingStarted-ImageClassification/FSBL/ai_fsbl.hex"
)


if os.getenv("ARONA_UNICODE") and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


@app.command()
def version() -> None:
    """Print the installed ARONA version."""
    typer.echo(__version__)


@app.command()
def discover() -> None:
    """Probe the local ST Edge AI target environment."""

    discovery = discover_stedgeai()
    typer.echo(render_discovery(discovery))


@app.command()
def doctor(
    serial_port: Annotated[
        str | None,
        typer.Option("--serial-port", help="Known ST-LINK virtual COM port, for example COM3."),
    ] = None,
) -> None:
    """Check local tools required for the STM32N6 MVP workflow."""

    discovery = discover_stedgeai()
    target = discovery.targets[0] if discovery.targets else None
    compiler = target.toolchain.compiler if target is not None else None
    programmer = resolve_programmer()
    external_loader = resolve_external_loader(programmer)
    make = resolve_make()
    gcc_directory = resolve_gcc_directory()
    objcopy = resolve_objcopy()
    signing_tool = resolve_signing_tool()
    detected_serial_port = serial_port or _detect_stlink_serial_port()

    checks = [
        (
            "ST Edge AI Core",
            compiler.version if compiler is not None else None,
            Path(compiler.executable) if compiler is not None and compiler.executable else None,
            compiler is not None and target is not None and str(target.availability) == "available",
        ),
        ("STM32CubeProgrammer", None, programmer, programmer is not None),
        ("NUCLEO external loader", None, external_loader, external_loader is not None),
        ("make", None, make, make is not None),
        ("Arm GCC", None, gcc_directory, gcc_directory is not None),
        ("Arm objcopy", None, objcopy, objcopy is not None),
        ("STM32 signing tool", None, signing_tool, signing_tool is not None),
        ("ST-LINK serial", detected_serial_port, None, detected_serial_port is not None),
    ]
    required_checks = [item for item in checks if item[0] != "ST-LINK serial"]
    ready = all(item[3] for item in required_checks)

    lines = [
        *render_banner("Doctor"),
        "",
        "Target",
        f"  board: {target.device.model if target is not None and target.device else 'unknown'}",
        (
            "  accelerator: "
            f"{target.device.accelerator if target is not None and target.device else 'unknown'}"
        ),
        "",
        "Checks",
    ]
    for name, version, path, ok in checks:
        detail = version or (path.as_posix() if path is not None else "missing")
        lines.append(f"  {_ok_icon(ok)} {name}: {detail}")
    if detected_serial_port is None:
        lines.append(
            "  ! warning: serial port was not auto-detected; "
            "pass --serial-port COMx during validation"
        )
    if target is not None:
        for issue in target.issues:
            lines.append(f"  ! warning: {issue}")
    lines.extend(
        [
            "",
            "Result",
            "  ready for optimize/deploy" if ready else "  missing required tools",
        ]
    )
    typer.echo("\n".join(lines))
    if not ready:
        raise typer.Exit(1)


@app.command()
def analyze(
    model: Annotated[
        Path,
        typer.Argument(help="Path to the ONNX model to analyze."),
    ],
    compiler_log: Annotated[
        Path,
        typer.Option(
            "--compiler-log",
            help="Captured stedgeai compiler log to parse as the baseline evidence.",
        ),
    ],
    output_directory: Annotated[
        Path,
        typer.Option(
            "--output-directory",
            "-o",
            help="Directory in which the run report and Markdown report are written.",
        ),
    ] = Path("outputs"),
) -> None:
    """Analyze an ONNX model and captured baseline compiler evidence."""

    report = analyze_model(model, compiler_log=compiler_log, output_directory=output_directory)
    run_directory = output_directory / report.run_id
    _write_run_artifacts(report, run_directory)
    typer.echo(render_run_report(report))
    typer.echo(f"\nArtifacts written to {run_directory.as_posix()}")


@app.command()
def optimize(
    model: Annotated[
        Path,
        typer.Argument(help="Path to the ONNX model to optimize."),
    ],
    compiler_log: Annotated[
        Path | None,
        typer.Option(
            "--compiler-log",
            help="Optional captured baseline stedgeai log; otherwise compile live.",
        ),
    ] = None,
    candidate_compiler_log: Annotated[
        Path | None,
        typer.Option(
            "--candidate-compiler-log",
            help="Optional captured candidate stedgeai log; otherwise compile live.",
        ),
    ] = None,
    target: Annotated[
        str,
        typer.Option(
            "--target",
            help="Optimization backend target. The MVP supports only 'stedgeai'.",
        ),
    ] = "stedgeai",
    validation_input: Annotated[
        Path | None,
        typer.Option(
            "--validation-input",
            help=(
                "Optional validation input directory kept in the run contract; "
                "the MVP ArgMax validator still uses deterministic generated inputs."
            ),
        ),
    ] = None,
    deploy: Annotated[
        bool,
        typer.Option(
            "--deploy",
            help=(
                "Run STM32N6 generate/build/program/validate, or attach --deployment-result "
                "when an existing validation result is supplied."
            ),
        ),
    ] = False,
    deployment_result: Annotated[
        Path | None,
        typer.Option(
            "--deployment-result",
            help="Existing deployment-result.json produced by 'arona deployment validate'.",
        ),
    ] = None,
    deployment_application: Annotated[
        DeploymentApplication,
        typer.Option("--deployment-application", help="STM32N6 application used for --deploy."),
    ] = DeploymentApplication.IMAGE_CLASSIFICATION,
    application_directory: Annotated[
        Path,
        typer.Option(
            "--application-directory",
            help="Official Application/NUCLEO-N657X0-Q directory used by --deploy.",
        ),
    ] = DEFAULT_IMAGE_CLASSIFICATION_APPLICATION,
    model_support_directory: Annotated[
        Path,
        typer.Option(
            "--model-support-directory",
            help="Official Model directory containing user_neuralart_NUCLEO-N657X0-Q.json.",
        ),
    ] = DEFAULT_IMAGE_CLASSIFICATION_MODEL_SUPPORT,
    fsbl: Annotated[
        Path,
        typer.Option("--fsbl", help="FSBL hex programmed before the selected application."),
    ] = DEFAULT_IMAGE_CLASSIFICATION_FSBL,
    serial_port: Annotated[
        str,
        typer.Option("--serial-port", help="ST-LINK virtual COM port used for --deploy validate."),
    ] = "COM5",
    inference_count: Annotated[
        int,
        typer.Option("--inference-count", min=1, help="Required target inference records."),
    ] = 5,
    capture_seconds: Annotated[
        float,
        typer.Option("--capture-seconds", min=0.1, help="UART capture duration after programming."),
    ] = 30.0,
    expected_model_name: Annotated[
        str | None,
        typer.Option("--expected-model-name", help="Required model identity in UART telemetry."),
    ] = None,
    expected_input_fnv1a: Annotated[
        str | None,
        typer.Option(
            "--expected-input-fnv1a",
            help="Require deterministic fixed-input hash in UART telemetry.",
        ),
    ] = None,
    build_top: Annotated[
        str,
        typer.Option("--build-top", help="Relative Make build directory name for --deploy."),
    ] = "build-arona-optimize",
    screen_interface: Annotated[
        str,
        typer.Option("--screen-interface", help="NUCLEO display interface: UVCL or SPI."),
    ] = "UVCL",
    jobs: Annotated[
        int,
        typer.Option("--jobs", min=1, max=32, help="Maximum parallel Make jobs for --deploy."),
    ] = 8,
    validation_samples: Annotated[
        int,
        typer.Option(
            "--validation-samples",
            min=1,
            help="Number of deterministic random inputs used for equivalence validation.",
        ),
    ] = 10,
    validation_seed: Annotated[
        int,
        typer.Option("--validation-seed", help="Random seed used for validation inputs."),
    ] = 260821,
    output_directory: Annotated[
        Path,
        typer.Option("--output-directory", "-o"),
    ] = Path("outputs"),
) -> None:
    """Run the MVP compiler-validated terminal ArgMax optimization pipeline."""

    if target != "stedgeai":
        raise typer.BadParameter(
            "The MVP optimize pipeline currently supports only --target stedgeai"
        )
    if screen_interface not in {"UVCL", "SPI"}:
        raise typer.BadParameter("--screen-interface must be UVCL or SPI")
    if validation_input is not None and not validation_input.exists():
        raise typer.BadParameter(f"--validation-input does not exist: {validation_input}")

    report = optimize_model(
        model,
        output_directory=output_directory,
        baseline_compiler_log=compiler_log,
        candidate_compiler_log=candidate_compiler_log,
        validation_samples=validation_samples,
        validation_seed=validation_seed,
    )
    run_directory = output_directory / report.run_id
    if deploy and deployment_result is None:
        report = report.model_copy(
            update={
                "deployment": _run_live_deployment(
                    report,
                    model,
                    run_directory,
                    application=deployment_application,
                    application_directory=application_directory,
                    model_support_directory=model_support_directory,
                    fsbl=fsbl,
                    serial_port=serial_port,
                    inference_count=inference_count,
                    capture_seconds=capture_seconds,
                    expected_model_name=expected_model_name,
                    expected_input_fnv1a=expected_input_fnv1a,
                    build_top=build_top,
                    screen_interface=screen_interface,
                    jobs=jobs,
                )
            }
        )
    elif deployment_result is not None:
        report = report.model_copy(
            update={"deployment": _load_deployment_result(deployment_result)}
        )
    _write_run_artifacts(report, run_directory)
    typer.echo(render_run_report(report))
    if validation_input is not None:
        typer.echo(
            "Validation input directory recorded for reproducibility; "
            "terminal ArgMax equivalence used deterministic generated inputs."
        )
    typer.echo(f"Artifacts written to {run_directory.as_posix()}")
    if (
        deploy
        and report.deployment is not None
        and report.deployment.status != StageStatus.SUCCEEDED
    ):
        raise typer.Exit(1)


@schema_app.command("export")
def export_schema(
    output_directory: Annotated[
        Path,
        typer.Option(
            "--output-directory",
            "-o",
            help="Directory in which versioned JSON Schema files are written.",
        ),
    ] = Path("schemas/v0.1.0"),
) -> None:
    """Export versioned JSON Schemas used by backend, pipeline, and CLI."""
    written_files = export_json_schemas(output_directory)
    for path in written_files:
        typer.echo(path.as_posix())


def _write_run_artifacts(report: RunReport, run_directory: Path) -> None:
    run_directory.mkdir(parents=True, exist_ok=True)
    (run_directory / "compiler").mkdir(parents=True, exist_ok=True)
    (run_directory / "run-report.json").write_text(
        report.model_dump_json(indent=2) + "\n",
        encoding="utf-8",
    )
    if report.baseline is not None:
        (run_directory / "original-analysis.json").write_text(
            report.baseline.model_dump_json(indent=2) + "\n",
            encoding="utf-8",
        )
    if report.optimized is not None:
        (run_directory / "optimized-analysis.json").write_text(
            report.optimized.model_dump_json(indent=2) + "\n",
            encoding="utf-8",
        )
    if report.rewrites:
        rewrite_json = (
            "[\n"
            + ",\n".join(rewrite.model_dump_json(indent=2) for rewrite in report.rewrites)
            + "\n]\n"
        )
        (run_directory / "rewrite-history.json").write_text(rewrite_json, encoding="utf-8")
    if report.deployment is not None:
        deployment_directory = run_directory / "deployment"
        deployment_directory.mkdir(parents=True, exist_ok=True)
        (deployment_directory / "deployment-result.json").write_text(
            report.deployment.model_dump_json(indent=2) + "\n",
            encoding="utf-8",
        )
        (run_directory / "deployment-analysis.json").write_text(
            report.deployment.model_dump_json(indent=2) + "\n",
            encoding="utf-8",
        )
    (run_directory / "report.md").write_text(
        render_markdown_report(report),
        encoding="utf-8",
    )


def _load_deployment_result(path: Path) -> DeploymentResult:
    if not path.is_file():
        raise typer.BadParameter(f"--deployment-result does not exist: {path}")
    return DeploymentResult.model_validate_json(path.read_text(encoding="utf-8"))


def _run_live_deployment(
    report: RunReport,
    requested_model: Path,
    run_directory: Path,
    *,
    application: DeploymentApplication,
    application_directory: Path,
    model_support_directory: Path,
    fsbl: Path,
    serial_port: str,
    inference_count: int,
    capture_seconds: float,
    expected_model_name: str | None,
    expected_input_fnv1a: str | None,
    build_top: str,
    screen_interface: str,
    jobs: int,
) -> DeploymentResult:
    selected_model = _selected_deployment_model(report, requested_model, run_directory)
    deployment_directory = run_directory / "deployment"
    config = NucleoDeploymentConfig(
        application=application,
        serial_port=serial_port,
        timeout_seconds=600,
    )
    deployer = Stm32N6Deployer()

    typer.echo("\nDeployment")
    typer.echo("  - codegen: generating model files")
    generate_result = deployer.generate(
        config,
        selected_model,
        model_support_directory,
        deployment_directory / "generate",
    )
    results = [generate_result]
    typer.echo(f"  {_stage_icon(generate_result.status)} codegen: {generate_result.status}")
    if generate_result.status != StageStatus.SUCCEEDED:
        return _merge_deployment_results(results, config)

    generated_model_directory = deployment_directory / "generate/model-files"
    typer.echo("  - link: building and signing official application")
    build_result = deployer.build(
        config,
        application_directory,
        deployment_directory / "build",
        jobs=jobs,
        build_top=build_top,
        model_directory=generated_model_directory,
        screen_interface=screen_interface,
    )
    results.append(build_result)
    typer.echo(f"  {_stage_icon(build_result.status)} link: {build_result.status}")
    if build_result.status != StageStatus.SUCCEEDED:
        return _merge_deployment_results(results, config)

    signed_application = (
        application_directory / build_top / "Application/NUCLEO-N657X0-Q/Project_sign.hex"
    )
    network_data = generated_model_directory / "network_data.hex"
    typer.echo("  - programming: flashing FSBL, application, and network data")
    program_result = deployer.program(
        config,
        [
            FirmwareImage(fsbl, "FSBL"),
            FirmwareImage(signed_application, "Signed NUCLEO application"),
            FirmwareImage(network_data, "External flash network data"),
        ],
        deployment_directory / "program",
        model_path=selected_model,
    )
    results.append(program_result)
    typer.echo(f"  {_stage_icon(program_result.status)} programming: {program_result.status}")
    if program_result.status == StageStatus.FAILED:
        return _merge_deployment_results(results, config)

    typer.echo(
        "\nProgramming completed. Move JP2 to position 1 (flash boot), "
        f"power-cycle the board, and wait for {serial_port} to reconnect."
    )
    if not typer.confirm("Continue with UART inference validation?", default=False):
        return _merge_deployment_results(results, config)

    typer.echo("  - validation: reading UART inference telemetry")
    validate_result = deployer.validate_serial(
        NucleoDeploymentConfig(
            application=application,
            serial_port=serial_port,
            boot_mode="flash",
            timeout_seconds=600,
        ),
        deployment_directory / "validate",
        minimum_inferences=inference_count,
        capture_seconds=capture_seconds,
        expected_model_name=expected_model_name or selected_model.stem,
        expected_input_fnv1a=expected_input_fnv1a,
    )
    results.append(validate_result)
    typer.echo(f"  {_stage_icon(validate_result.status)} validation: {validate_result.status}")
    return _merge_deployment_results(results, config)


def _selected_deployment_model(
    report: RunReport, requested_model: Path, run_directory: Path
) -> Path:
    optimized_model = run_directory / "optimized-model.onnx"
    if (
        report.decision is not None
        and report.decision.selected == "optimized"
        and optimized_model.is_file()
    ):
        return optimized_model
    return requested_model


def _merge_deployment_results(
    results: list[DeploymentResult],
    config: NucleoDeploymentConfig,
) -> DeploymentResult:
    stages = [stage for result in results for stage in result.stages]
    firmware = [artifact for result in results for artifact in result.firmware]
    observations = [item for result in results for item in result.observations]
    failed = next((result for result in results if result.status == StageStatus.FAILED), None)
    succeeded = results and results[-1].status == StageStatus.SUCCEEDED
    status = (
        StageStatus.FAILED
        if failed is not None
        else StageStatus.SUCCEEDED
        if succeeded
        else StageStatus.WARNING
    )
    reason = results[-1].reason if results else "Deployment did not run."
    return DeploymentResult(
        status=status,
        application=config.application,
        board=config.expected_board,
        serial_port=config.serial_port,
        boot_mode="flash" if succeeded else config.boot_mode,
        model=next((result.model for result in results if result.model is not None), None),
        firmware=firmware,
        stages=stages,
        observations=observations,
        reason=reason,
    )


@deployment_app.command("instrument")
def deployment_instrument(
    application: Annotated[
        DeploymentApplication,
        typer.Option("--application", help="Official STM32N6 application type."),
    ],
    application_directory: Annotated[
        Path,
        typer.Argument(help="Official Application/NUCLEO-N657X0-Q directory."),
    ],
) -> None:
    """Add explicit, idempotent per-inference UART telemetry to an official application."""

    try:
        source_path, changed = instrument_uart_telemetry(application, application_directory)
    except TelemetryInstrumentationError as error:
        raise typer.BadParameter(str(error)) from error
    action = "instrumented" if changed else "already instrumented"
    typer.echo(f"{source_path.as_posix()}: {action}")


@deployment_app.command("fixed-input")
def deployment_fixed_input(
    application: Annotated[
        DeploymentApplication,
        typer.Option("--application", help="Official STM32N6 application type."),
    ],
    application_directory: Annotated[
        Path,
        typer.Argument(help="Official Application/NUCLEO-N657X0-Q directory."),
    ],
) -> None:
    """Use deterministic input for real inference when a camera is unavailable."""

    try:
        source_path, changed = instrument_fixed_input_smoke(application, application_directory)
    except TelemetryInstrumentationError as error:
        raise typer.BadParameter(str(error)) from error
    action = "fixed-input smoke mode enabled" if changed else "already enabled"
    typer.echo(f"{source_path.as_posix()}: {action}")


@deployment_app.command("configure")
def deployment_configure(
    application: Annotated[
        DeploymentApplication,
        typer.Option("--application", help="Fixed MVP application type."),
    ],
    application_directory: Annotated[
        Path,
        typer.Argument(help="Official Application/NUCLEO-N657X0-Q directory."),
    ],
) -> None:
    """Configure the official application for the selected fixed MVP model."""

    try:
        config_path = configure_mvp_application(application, application_directory)
    except ValueError as error:
        raise typer.BadParameter(str(error)) from error
    typer.echo(config_path.as_posix())


@deployment_app.command("build")
def deployment_build(
    application: Annotated[
        DeploymentApplication,
        typer.Option("--application", help="Official STM32N6 application type."),
    ],
    application_directory: Annotated[
        Path,
        typer.Argument(help="Official Application/NUCLEO-N657X0-Q directory."),
    ],
    output_directory: Annotated[
        Path,
        typer.Option("--output-directory", "-o", help="Deployment evidence directory."),
    ] = Path("outputs/deployment"),
    screen_interface: Annotated[
        str,
        typer.Option("--screen-interface", help="NUCLEO display interface: UVCL or SPI."),
    ] = "UVCL",
    jobs: Annotated[
        int,
        typer.Option("--jobs", min=1, max=32, help="Maximum parallel Make jobs."),
    ] = 8,
    build_top: Annotated[
        str,
        typer.Option(
            "--build-top",
            help="Relative Make build directory name; use a new name for a clean build.",
        ),
    ] = "build",
    model_directory: Annotated[
        Path | None,
        typer.Option(
            "--model-directory",
            help="Generated network.c/stai_network.c model directory overriding MODEL_DIR.",
        ),
    ] = None,
) -> None:
    """Build and sign an official NUCLEO-N657X0-Q application."""

    if screen_interface not in {"UVCL", "SPI"}:
        raise typer.BadParameter("--screen-interface must be UVCL or SPI")
    result = Stm32N6Deployer().build(
        NucleoDeploymentConfig(application=application),
        application_directory,
        output_directory,
        jobs=jobs,
        build_top=build_top,
        model_directory=model_directory,
        screen_interface=screen_interface,
    )
    typer.echo(_render_deployment_result(result))
    if result.status == "failed":
        raise typer.Exit(1)


@deployment_app.command("sync-runtime")
def deployment_sync_runtime(
    application_directory: Annotated[
        Path,
        typer.Argument(help="Official Application/NUCLEO-N657X0-Q directory."),
    ],
    core_directory: Annotated[
        Path,
        typer.Option(
            "--core-directory",
            help="Installed STEdgeAI Core root containing Middlewares/ST/AI.",
        ),
    ],
    output_directory: Annotated[
        Path,
        typer.Option("--output-directory", "-o", help="Runtime-sync evidence directory."),
    ] = Path("outputs/deployment/runtime-sync"),
) -> None:
    """Synchronize and verify the official application runtime against STEdgeAI Core."""

    try:
        manifest_path = sync_stedgeai_runtime(
            application_directory,
            core_directory,
            output_directory,
        )
    except ValueError as error:
        raise typer.BadParameter(str(error)) from error
    typer.echo(manifest_path.as_posix())


@deployment_app.command("generate")
def deployment_generate(
    model: Annotated[Path, typer.Argument(help="Selected ONNX model to generate.")],
    application: Annotated[
        DeploymentApplication,
        typer.Option("--application", help="Official STM32N6 application type."),
    ],
    model_support_directory: Annotated[
        Path,
        typer.Option(
            "--model-support-directory",
            help="Official repository Model directory containing the NUCLEO Neural-ART profile.",
        ),
    ],
    output_directory: Annotated[
        Path,
        typer.Option("--output-directory", "-o", help="Generated model and evidence directory."),
    ] = Path("outputs/deployment-generation"),
) -> None:
    """Generate selected-model sources and external-flash data with STEdgeAI Core."""

    result = Stm32N6Deployer().generate(
        NucleoDeploymentConfig(application=application, timeout_seconds=600),
        model,
        model_support_directory,
        output_directory,
    )
    typer.echo(_render_deployment_result(result))
    if result.status != "succeeded":
        raise typer.Exit(1)


@deployment_app.command("program")
def deployment_program(
    firmware: Annotated[
        list[str],
        typer.Argument(help="One or more PATH or PATH@0xADDRESS firmware specifications."),
    ],
    application: Annotated[
        DeploymentApplication,
        typer.Option("--application", help="Application represented by the firmware."),
    ],
    model: Annotated[
        Path | None,
        typer.Option("--model", help="Model associated with the generated firmware."),
    ] = None,
    output_directory: Annotated[
        Path,
        typer.Option("--output-directory", "-o", help="Deployment evidence directory."),
    ] = Path("outputs/deployment"),
    boot_mode: Annotated[
        str,
        typer.Option(
            "--boot-mode",
            help="Physical board mode asserted by the operator; programming requires development.",
        ),
    ] = "development",
) -> None:
    """Probe the exact NUCLEO board and program firmware with captured logs."""

    images = [_parse_firmware_spec(value) for value in firmware]
    result = Stm32N6Deployer().program(
        NucleoDeploymentConfig(
            application=application,
            boot_mode=boot_mode,
        ),
        images,
        output_directory,
        model_path=model,
    )
    typer.echo(_render_deployment_result(result))
    if result.status == "failed":
        raise typer.Exit(1)


@deployment_app.command("backup")
def deployment_backup(
    application: Annotated[
        DeploymentApplication,
        typer.Option("--application", help="Application to be deployed after the backup."),
    ],
    output_directory: Annotated[
        Path,
        typer.Option("--output-directory", "-o", help="Backup and evidence directory."),
    ] = Path("outputs/deployment-backup"),
    timeout_seconds: Annotated[
        int,
        typer.Option(
            "--timeout-seconds",
            min=60,
            help="Timeout for uploading the complete 64 MiB external flash.",
        ),
    ] = 600,
) -> None:
    """Back up the complete 64 MiB NUCLEO external flash after an exact-board probe."""

    result = Stm32N6Deployer().backup_external_flash(
        NucleoDeploymentConfig(application=application, timeout_seconds=timeout_seconds),
        output_directory,
    )
    typer.echo(_render_deployment_result(result))
    if result.status != "succeeded":
        raise typer.Exit(1)


@deployment_app.command("validate")
def deployment_validate(
    application: Annotated[
        DeploymentApplication,
        typer.Option("--application", help="Running application type."),
    ],
    output_directory: Annotated[
        Path,
        typer.Option("--output-directory", "-o", help="Deployment evidence directory."),
    ] = Path("outputs/deployment-validation"),
    serial_port: Annotated[
        str,
        typer.Option("--serial-port", help="ST-LINK virtual COM port."),
    ] = "COM5",
    inference_count: Annotated[
        int,
        typer.Option("--inference-count", min=1, help="Required explicit inference records."),
    ] = 5,
    capture_seconds: Annotated[
        float,
        typer.Option("--capture-seconds", min=0.1, help="UART capture duration."),
    ] = 30.0,
    expected_model_name: Annotated[
        str | None,
        typer.Option("--expected-model-name", help="Required model identity in UART telemetry."),
    ] = None,
    expected_input_fnv1a: Annotated[
        str | None,
        typer.Option(
            "--expected-input-fnv1a",
            help="Require every inference to report this deterministic fixed-input hash.",
        ),
    ] = None,
) -> None:
    """Validate explicit inference telemetry after flash boot and power-cycle."""

    result = Stm32N6Deployer().validate_serial(
        NucleoDeploymentConfig(
            application=application,
            serial_port=serial_port,
            boot_mode="flash",
        ),
        output_directory,
        minimum_inferences=inference_count,
        capture_seconds=capture_seconds,
        expected_model_name=expected_model_name,
        expected_input_fnv1a=expected_input_fnv1a,
    )
    typer.echo(_render_deployment_result(result))
    if result.status != "succeeded":
        raise typer.Exit(1)


def _detect_stlink_serial_port() -> str | None:
    try:
        from serial.tools import list_ports
    except ImportError:
        return None
    for port in list_ports.comports():
        text = " ".join(
            value
            for value in (port.device, port.description, port.hwid, port.manufacturer)
            if value
        ).lower()
        if "st-link" in text or "stlink" in text or "vid:pid=0483:3754" in text:
            return str(port.device)
    return None


def _ok_icon(ok: bool) -> str:
    return "OK" if ok else "FAIL"


def _stage_icon(status: object) -> str:
    if str(status) == "succeeded":
        return "OK"
    if str(status) == "failed":
        return "FAIL"
    return "!"


def _parse_firmware_spec(value: str) -> FirmwareImage:
    path_value, separator, parsed_address = value.rpartition("@")
    address: str | None
    if separator:
        address = parsed_address
    else:
        path_value = value
        address = None
    path = Path(path_value)
    return FirmwareImage(
        path=path,
        address=address,
        description=f"Firmware image {path.name}",
    )


def _render_deployment_result(result: object) -> str:
    if not isinstance(result, DeploymentResult):
        raise TypeError("result must be a DeploymentResult")
    return "\n".join(render_deployment_block(result))

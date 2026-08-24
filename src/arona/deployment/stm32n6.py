"""Build, program, and validate official STM32N6 applications."""

from __future__ import annotations

import json
import os
import re
import shutil
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from arona.backends.stedgeai.adapter import _resolve_stedgeai_executable
from arona.contracts.v1 import (
    ArtifactKind,
    ArtifactRef,
    DeploymentApplication,
    DeploymentResult,
    DeploymentStage,
    DeploymentStageName,
    InferenceObservation,
    StageStatus,
)
from arona.deployment.commands import (
    CommandOutcome,
    CommandRunner,
    SubprocessCommandRunner,
    first_error,
    write_command_log,
)
from arona.onnx_frontend.checksum import sha256_file

EXPECTED_BOARD = "NUCLEO-N657X0-Q"
DEFAULT_SERIAL_PORT = "COM5"
NUCLEO_EXTERNAL_FLASH_ADDRESS = "0x70000000"
NUCLEO_EXTERNAL_FLASH_SIZE_BYTES = 64 * 1024 * 1024
INFERENCE_PATTERN = re.compile(
    r"ARONA_INFERENCE(?:\s+seq=(?P<sequence>\d+))?\s+latency_ms=(?P<latency>\d+(?:\.\d+)?)"
    r"(?:\s+(?P<summary>.*))?",
    re.IGNORECASE,
)
STEDGEAI_RUNTIME_COMPONENTS = (
    "Inc",
    "Lib",
    "Misc",
    "Npu",
    "Reloc",
    "SystemPerformance",
)


@dataclass(frozen=True)
class FirmwareImage:
    path: Path
    description: str
    address: str | None = None


@dataclass(frozen=True)
class NucleoDeploymentConfig:
    application: DeploymentApplication
    serial_port: str = DEFAULT_SERIAL_PORT
    boot_mode: str = "development"
    expected_board: str = EXPECTED_BOARD
    programmer: Path | None = None
    external_loader: Path | None = None
    timeout_seconds: int = 180


class Stm32N6Deployer:
    def __init__(self, runner: CommandRunner | None = None) -> None:
        self.runner = runner or SubprocessCommandRunner()

    def build(
        self,
        config: NucleoDeploymentConfig,
        application_directory: Path,
        output_directory: Path,
        *,
        make_executable: Path | None = None,
        gcc_directory: Path | None = None,
        signing_tool: Path | None = None,
        jobs: int = 8,
        build_top: str = "build",
        model_directory: Path | None = None,
        screen_interface: str = "UVCL",
    ) -> DeploymentResult:
        """Build and sign an official NUCLEO application without programming it."""

        output_directory.mkdir(parents=True, exist_ok=True)
        make = make_executable or resolve_make()
        gcc = gcc_directory or resolve_gcc_directory()
        signer = signing_tool or resolve_signing_tool()
        missing = [
            name
            for name, value in (("make", make), ("GCC", gcc), ("signing tool", signer))
            if value is None
        ]
        if missing:
            return _write_result(
                _failed_result(config, f"Missing build tools: {', '.join(missing)}."),
                output_directory,
            )
        if not (application_directory / "Makefile").is_file():
            return _write_result(
                _failed_result(config, f"Official Makefile not found: {application_directory}"),
                output_directory,
            )
        if re.fullmatch(r"[A-Za-z0-9._-]+", build_top) is None:
            return _write_result(
                _failed_result(config, f"Invalid build directory name: {build_top}."),
                output_directory,
            )
        assert make is not None and gcc is not None and signer is not None

        command = [
            str(make),
            f"-j{jobs}",
            "sign",
            f"GCC_PATH={gcc.as_posix()}",
            # STM32 Signing Tool 2.21+ requires the N6 v2.3 payload to start
            # at the 0x400 boundary.  Passing the option through SIGNER keeps
            # the official Makefile as the source of the remaining sign args.
            f"SIGNER={signer.as_posix()} -align",
            f"SCR_LIB_SCREEN_ITF={screen_interface}",
            f"BUILD_TOP={build_top}",
        ]
        network_runtime = resolve_network_runtime_library(application_directory)
        if network_runtime is not None:
            command.append(f"LIBS=-lc -lm -lnosys -l:{network_runtime.name}")
        if model_directory is not None:
            if not model_directory.is_dir():
                return _write_result(
                    _failed_result(
                        config, f"Generated model directory is missing: {model_directory}"
                    ),
                    output_directory,
                )
            try:
                relative_model_directory = os.path.relpath(
                    model_directory.resolve(),
                    start=application_directory.resolve(),
                )
            except ValueError:
                return _write_result(
                    _failed_result(
                        config,
                        "Generated model directory must be on the same drive as the application.",
                    ),
                    output_directory,
                )
            command.append(f"MODEL_DIR={Path(relative_model_directory).as_posix()}")
        started_at = datetime.now(UTC)
        environment = os.environ.copy()
        environment["PATH"] = os.pathsep.join(
            [
                str(make.parent),
                str(gcc),
                str(signer.parent),
                environment.get("PATH", ""),
            ]
        )
        outcome = self.runner.run(
            command,
            working_directory=application_directory,
            timeout_seconds=config.timeout_seconds,
            environment=environment,
        )
        log = write_command_log(outcome, output_directory / "build.json")
        artifacts = [_file_artifact(log, ArtifactKind.OTHER, "Captured build command")]
        signed_hex = (
            application_directory / build_top / "Application/NUCLEO-N657X0-Q/Project_sign.hex"
        )
        succeeded = outcome.exit_code == 0 and signed_hex.is_file()
        if succeeded:
            artifacts.append(
                _file_artifact(signed_hex, ArtifactKind.DEPLOYABLE, "Signed NUCLEO application")
            )
        stage = _stage(
            DeploymentStageName.LINK,
            outcome,
            started_at,
            artifacts,
            succeeded=succeeded,
        )
        result = DeploymentResult(
            status=StageStatus.SUCCEEDED if succeeded else StageStatus.FAILED,
            application=config.application,
            board=config.expected_board,
            serial_port=config.serial_port,
            boot_mode=config.boot_mode,
            stages=[stage],
            firmware=artifacts[1:] if succeeded else [],
            reason=(
                "Official application built and signed; board programming was not requested."
                if succeeded
                else stage.first_error or "Build did not produce Project_sign.hex."
            ),
        )
        return _write_result(result, output_directory)

    def generate(
        self,
        config: NucleoDeploymentConfig,
        model_path: Path,
        model_support_directory: Path,
        output_directory: Path,
        *,
        stedgeai_executable: Path | None = None,
        objcopy_executable: Path | None = None,
    ) -> DeploymentResult:
        """Generate and package model files for an official NUCLEO application."""

        output_directory.mkdir(parents=True, exist_ok=True)
        stedgeai_value = (
            str(stedgeai_executable) if stedgeai_executable else _resolve_stedgeai_executable()
        )
        stedgeai = Path(stedgeai_value) if stedgeai_value else None
        objcopy = objcopy_executable or resolve_objcopy()
        profile = model_support_directory / "user_neuralart_NUCLEO-N657X0-Q.json"
        if not model_path.is_file():
            return _write_result(
                _failed_result(config, f"Model does not exist: {model_path}."),
                output_directory,
            )
        if not profile.is_file():
            return _write_result(
                _failed_result(config, f"NUCLEO Neural-ART profile is missing: {profile}."),
                output_directory,
            )
        if stedgeai is None or not stedgeai.is_file() or objcopy is None:
            return _write_result(
                _failed_result(config, "STEdgeAI Core or Arm objcopy is missing."),
                output_directory,
            )

        generated_directory = (output_directory / "stedgeai-output").resolve()
        workspace = (output_directory / "workspace").resolve()
        staged_directory = (output_directory / "model-files").resolve()
        generated_directory.mkdir(parents=True, exist_ok=True)
        staged_directory.mkdir(parents=True, exist_ok=True)
        output_type = (
            "float32"
            if config.application == DeploymentApplication.IMAGE_CLASSIFICATION
            else "int8"
        )
        command = [
            str(stedgeai),
            "generate",
            "--model",
            str(model_path.resolve()),
            "--target",
            "stm32n6",
            "--type",
            "onnx",
            "--st-neural-art",
            f"default@{profile.resolve().as_posix()}",
            "--input-data-type",
            "uint8",
            "--output-data-type",
            output_type,
            "--inputs-ch-position",
            "chlast",
            "--workspace",
            str(workspace),
            "--output",
            str(generated_directory),
            "--with-report",
        ]
        started_at = datetime.now(UTC)
        outcome = self.runner.run(
            command,
            working_directory=model_support_directory,
            timeout_seconds=config.timeout_seconds,
        )
        log = write_command_log(outcome, output_directory / "generate.json")
        required_names = (
            "network.c",
            "network_ecblobs.h",
            "stai_network.c",
            "stai_network.h",
            "network_atonbuf.xSPI2.raw",
        )
        generated_files = [generated_directory / name for name in required_names]
        generated_ok = outcome.exit_code == 0 and all(path.is_file() for path in generated_files)
        codegen_artifacts = [
            _file_artifact(log, ArtifactKind.COMPILER_LOG, "STEdgeAI generate log")
        ]
        if generated_ok:
            for source in generated_files:
                destination = staged_directory / source.name
                shutil.copy2(source, destination)
                codegen_artifacts.append(
                    _file_artifact(destination, ArtifactKind.OTHER, "Generated model file")
                )
        stages = [
            _stage(
                DeploymentStageName.CODEGEN,
                outcome,
                started_at,
                codegen_artifacts,
                succeeded=generated_ok,
                error_override=(
                    None
                    if generated_ok
                    else "STEdgeAI did not generate every required STM32N6 model file."
                ),
            )
        ]
        if not generated_ok:
            return _write_result(
                DeploymentResult(
                    status=StageStatus.FAILED,
                    application=config.application,
                    board=config.expected_board,
                    serial_port=config.serial_port,
                    model=_optional_model_artifact(model_path),
                    stages=stages,
                    reason=stages[-1].first_error,
                ),
                output_directory,
            )

        raw_weights = staged_directory / "network_atonbuf.xSPI2.raw"
        network_hex = staged_directory / "network_data.hex"
        package_command = [
            str(objcopy),
            "-I",
            "binary",
            str(raw_weights),
            "--change-addresses",
            "0x70380000",
            "-O",
            "ihex",
            str(network_hex),
        ]
        package_started = datetime.now(UTC)
        package_outcome = self.runner.run(
            package_command,
            working_directory=staged_directory,
            timeout_seconds=min(config.timeout_seconds, 60),
        )
        package_log = write_command_log(package_outcome, output_directory / "network-data.json")
        package_ok = package_outcome.exit_code == 0 and network_hex.is_file()
        package_artifacts = [
            _file_artifact(package_log, ArtifactKind.OTHER, "Network data packaging log")
        ]
        if package_ok:
            package_artifacts.append(
                _file_artifact(network_hex, ArtifactKind.DEPLOYABLE, "External flash network data")
            )
        stages.append(
            _stage(
                DeploymentStageName.LINK,
                package_outcome,
                package_started,
                package_artifacts,
                succeeded=package_ok,
                error_override=None if package_ok else "network_data.hex was not generated.",
            )
        )
        return _write_result(
            DeploymentResult(
                status=StageStatus.SUCCEEDED if package_ok else StageStatus.FAILED,
                application=config.application,
                board=config.expected_board,
                serial_port=config.serial_port,
                model=_optional_model_artifact(model_path),
                firmware=package_artifacts[1:] if package_ok else [],
                stages=stages,
                reason=(
                    "Model code and external-flash network data generated."
                    if package_ok
                    else stages[-1].first_error
                ),
            ),
            output_directory,
        )

    def program(
        self,
        config: NucleoDeploymentConfig,
        firmware: list[FirmwareImage],
        output_directory: Path,
        *,
        model_path: Path | None = None,
    ) -> DeploymentResult:
        """Probe the exact board, then program validated firmware images in order."""

        output_directory.mkdir(parents=True, exist_ok=True)
        invalid = _validate_program_request(config, firmware)
        if invalid is not None:
            return _write_result(_failed_result(config, invalid), output_directory)

        programmer = config.programmer or resolve_programmer()
        loader = config.external_loader or resolve_external_loader(programmer)
        if programmer is None or loader is None:
            return _write_result(
                _failed_result(config, "STM32CubeProgrammer or NUCLEO external loader is missing."),
                output_directory,
            )

        stages: list[DeploymentStage] = []
        probe_started = datetime.now(UTC)
        probe = self.runner.run(
            [str(programmer), "-c", "port=SWD", "mode=HOTPLUG"],
            working_directory=output_directory,
            timeout_seconds=min(config.timeout_seconds, 30),
        )
        probe_log = write_command_log(probe, output_directory / "probe.json")
        probed_board = _parse_board(probe.stdout)
        probe_ok = probe.exit_code == 0 and probed_board == config.expected_board
        stages.append(
            _stage(
                DeploymentStageName.INITIALIZATION,
                probe,
                probe_started,
                [_file_artifact(probe_log, ArtifactKind.OTHER, "Read-only board probe")],
                succeeded=probe_ok,
                error_override=_probe_error(probe, probed_board, config.expected_board),
            )
        )
        if not probe_ok:
            return _write_result(
                DeploymentResult(
                    status=StageStatus.FAILED,
                    application=config.application,
                    board=config.expected_board,
                    serial_port=config.serial_port,
                    boot_mode=config.boot_mode,
                    model=_optional_model_artifact(model_path),
                    stages=stages,
                    reason=stages[-1].first_error,
                ),
                output_directory,
            )

        firmware_artifacts: list[ArtifactRef] = []
        for index, image in enumerate(firmware, start=1):
            artifact = _file_artifact(image.path, ArtifactKind.DEPLOYABLE, image.description)
            firmware_artifacts.append(artifact)
            command = [
                str(programmer),
                "-c",
                "port=SWD",
                "mode=HOTPLUG",
                "-el",
                str(loader),
                "-hardRst",
            ]
            command.extend(["-w", str(image.path.resolve())])
            if image.address is not None:
                command.append(image.address)
            command.append("-v")
            started_at = datetime.now(UTC)
            outcome = self.runner.run(
                command,
                working_directory=output_directory,
                timeout_seconds=config.timeout_seconds,
            )
            log = write_command_log(outcome, output_directory / f"program-{index}.json")
            succeeded = outcome.exit_code == 0
            stages.append(
                _stage(
                    DeploymentStageName.PROGRAMMING,
                    outcome,
                    started_at,
                    [artifact, _file_artifact(log, ArtifactKind.OTHER, "Programming log")],
                    succeeded=succeeded,
                )
            )
            if not succeeded:
                break

        programmed = all(
            stage.status == StageStatus.SUCCEEDED
            for stage in stages
            if stage.stage == DeploymentStageName.PROGRAMMING
        ) and len(firmware_artifacts) == len(firmware)
        result = DeploymentResult(
            status=StageStatus.WARNING if programmed else StageStatus.FAILED,
            application=config.application,
            board=config.expected_board,
            serial_port=config.serial_port,
            boot_mode=config.boot_mode,
            model=_optional_model_artifact(model_path),
            firmware=firmware_artifacts,
            stages=stages,
            reason=(
                "Programming completed. Switch to flash boot, power-cycle, then run "
                "serial validation."
                if programmed
                else stages[-1].first_error or "Programming failed."
            ),
        )
        return _write_result(result, output_directory)

    def backup_external_flash(
        self,
        config: NucleoDeploymentConfig,
        output_directory: Path,
        *,
        address: str = NUCLEO_EXTERNAL_FLASH_ADDRESS,
        size_bytes: int = NUCLEO_EXTERNAL_FLASH_SIZE_BYTES,
    ) -> DeploymentResult:
        """Read the NUCLEO external flash before a potentially destructive deployment."""

        output_directory.mkdir(parents=True, exist_ok=True)
        if config.expected_board != EXPECTED_BOARD:
            return _write_result(
                _failed_result(config, f"Unsupported board: {config.expected_board}."),
                output_directory,
            )
        if config.boot_mode != "development":
            return _write_result(
                _failed_result(config, "External flash backup requires boot_mode=development."),
                output_directory,
            )
        if re.fullmatch(r"0x[0-9a-fA-F]{8}", address) is None or size_bytes <= 0:
            return _write_result(
                _failed_result(config, "Invalid external flash backup range."),
                output_directory,
            )

        programmer = config.programmer or resolve_programmer()
        loader = config.external_loader or resolve_external_loader(programmer)
        if programmer is None or loader is None:
            return _write_result(
                _failed_result(config, "STM32CubeProgrammer or NUCLEO external loader is missing."),
                output_directory,
            )

        stages: list[DeploymentStage] = []
        probe_started = datetime.now(UTC)
        probe = self.runner.run(
            [str(programmer), "-c", "port=SWD", "mode=HOTPLUG"],
            working_directory=output_directory,
            timeout_seconds=min(config.timeout_seconds, 30),
        )
        probe_log = write_command_log(probe, output_directory / "probe.json")
        probed_board = _parse_board(probe.stdout)
        probe_ok = probe.exit_code == 0 and probed_board == config.expected_board
        stages.append(
            _stage(
                DeploymentStageName.INITIALIZATION,
                probe,
                probe_started,
                [_file_artifact(probe_log, ArtifactKind.OTHER, "Read-only board probe")],
                succeeded=probe_ok,
                error_override=_probe_error(probe, probed_board, config.expected_board),
            )
        )
        if not probe_ok:
            return _write_result(
                DeploymentResult(
                    status=StageStatus.FAILED,
                    application=config.application,
                    board=config.expected_board,
                    serial_port=config.serial_port,
                    boot_mode=config.boot_mode,
                    stages=stages,
                    reason=stages[-1].first_error,
                ),
                output_directory,
            )

        backup_path = output_directory / f"external-flash-{address}-{size_bytes}.bin"
        command = [
            str(programmer),
            "-c",
            "port=SWD",
            "mode=HOTPLUG",
            "-el",
            str(loader),
            "-hardRst",
        ]
        command.extend(["-u", address, hex(size_bytes), str(backup_path.resolve())])
        started_at = datetime.now(UTC)
        outcome = self.runner.run(
            command,
            working_directory=output_directory,
            timeout_seconds=config.timeout_seconds,
        )
        log = write_command_log(outcome, output_directory / "backup.json")
        artifacts = [_file_artifact(log, ArtifactKind.OTHER, "External flash backup log")]
        backup_ok = (
            outcome.exit_code == 0
            and backup_path.is_file()
            and backup_path.stat().st_size == size_bytes
        )
        if backup_path.is_file():
            artifacts.append(
                _file_artifact(
                    backup_path, ArtifactKind.OTHER, "Pre-deployment external flash backup"
                )
            )
        stages.append(
            _stage(
                DeploymentStageName.VALIDATION,
                outcome,
                started_at,
                artifacts,
                succeeded=backup_ok,
                error_override=(
                    None
                    if backup_ok
                    else "External flash upload did not produce the expected-size backup."
                ),
            )
        )
        return _write_result(
            DeploymentResult(
                status=StageStatus.SUCCEEDED if backup_ok else StageStatus.FAILED,
                application=config.application,
                board=config.expected_board,
                serial_port=config.serial_port,
                boot_mode=config.boot_mode,
                stages=stages,
                reason=(
                    f"Backed up {size_bytes} bytes from {address}."
                    if backup_ok
                    else stages[-1].first_error
                ),
            ),
            output_directory,
        )

    def validate_serial(
        self,
        config: NucleoDeploymentConfig,
        output_directory: Path,
        *,
        minimum_inferences: int = 5,
        capture_seconds: float = 30.0,
        baud_rate: int = 115200,
        expected_model_name: str | None = None,
        expected_input_fnv1a: str | None = None,
    ) -> DeploymentResult:
        """Capture UART telemetry and require explicit per-inference evidence."""

        output_directory.mkdir(parents=True, exist_ok=True)
        started_at = datetime.now(UTC)
        try:
            lines = _capture_serial(
                config.serial_port,
                baud_rate=baud_rate,
                duration_seconds=capture_seconds,
            )
            error: str | None = None
        except Exception as caught:  # Serial backends expose platform-specific errors.
            lines = []
            error = str(caught)

        serial_log = output_directory / "serial.log"
        serial_log.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")
        observations = parse_inference_observations(lines)
        model_seen = expected_model_name is None or any(
            f"NN model: {expected_model_name}" in line or f"model={expected_model_name}" in line
            for line in lines
        )
        expected_hash = expected_input_fnv1a.lower() if expected_input_fnv1a else None
        fixed_input_seen = expected_hash is None or (
            bool(observations)
            and all(
                "input=fixed" in (observation.summary or "")
                and f"fnv1a={expected_hash}" in (observation.summary or "").lower()
                for observation in observations
            )
        )
        inference_succeeded = error is None and bool(observations)
        succeeded = (
            inference_succeeded
            and len(observations) >= minimum_inferences
            and model_seen
            and fixed_input_seen
        )
        if error is not None:
            reason = error
        elif not model_seen:
            reason = f"Expected model identity was not observed: {expected_model_name}."
        elif not fixed_input_seen:
            reason = f"Expected deterministic fixed input was not observed: fnv1a={expected_hash}."
        elif len(observations) < minimum_inferences:
            reason = (
                f"Observed {len(observations)} explicit inferences; {minimum_inferences} required."
            )
        else:
            reason = f"Observed {len(observations)} successful inference records."
        ended_at = datetime.now(UTC)
        inference_reason = error or (
            None if observations else "No explicit ARONA_INFERENCE telemetry was observed."
        )
        inference_stage = DeploymentStage(
            stage=DeploymentStageName.INFERENCE,
            status=StageStatus.SUCCEEDED if inference_succeeded else StageStatus.FAILED,
            started_at=started_at,
            ended_at=ended_at,
            duration_ms=(ended_at - started_at).total_seconds() * 1000,
            first_error=inference_reason,
            artifacts=[_file_artifact(serial_log, ArtifactKind.OTHER, "Captured UART output")],
        )
        validation_stage = DeploymentStage(
            stage=DeploymentStageName.VALIDATION,
            status=StageStatus.SUCCEEDED if succeeded else StageStatus.FAILED,
            started_at=ended_at,
            ended_at=ended_at,
            duration_ms=0,
            first_error=None if succeeded else reason,
        )
        return _write_result(
            DeploymentResult(
                status=StageStatus.SUCCEEDED if succeeded else StageStatus.FAILED,
                application=config.application,
                board=config.expected_board,
                serial_port=config.serial_port,
                boot_mode=config.boot_mode,
                stages=[inference_stage, validation_stage],
                observations=observations,
                reason=reason,
            ),
            output_directory,
        )


def parse_inference_observations(lines: list[str]) -> list[InferenceObservation]:
    observations: list[InferenceObservation] = []
    for line in lines:
        match = INFERENCE_PATTERN.search(line)
        if match is None:
            continue
        observations.append(
            InferenceObservation(
                sequence=(
                    int(match.group("sequence"))
                    if match.group("sequence")
                    else len(observations) + 1
                ),
                observed_at=datetime.now(UTC),
                success=True,
                latency_ms=float(match.group("latency")),
                summary=(match.group("summary") or "Inference completed.").strip(),
            )
        )
    return observations


def sync_stedgeai_runtime(
    application_directory: Path,
    core_directory: Path,
    output_directory: Path,
) -> Path:
    """Overlay an official application checkout with the selected STEdgeAI Core runtime."""

    application_directory = application_directory.resolve()
    core_directory = core_directory.resolve()
    if (
        application_directory.name != EXPECTED_BOARD
        or not (application_directory / "Makefile").is_file()
    ):
        raise ValueError(
            f"Application directory must be an official Application/{EXPECTED_BOARD} directory."
        )

    repository_root = application_directory.parent.parent
    source_root = core_directory / "Middlewares/ST/AI"
    destination_root = repository_root / "Middlewares/stedgeai-lib"
    missing = [name for name in STEDGEAI_RUNTIME_COMPONENTS if not (source_root / name).is_dir()]
    if missing:
        raise ValueError(
            f"STEdgeAI Core runtime is incomplete at {source_root}: {', '.join(missing)}."
        )
    if not destination_root.is_dir():
        raise ValueError(f"Official stedgeai-lib directory is missing: {destination_root}.")

    component_counts: dict[str, int] = {}
    verified_files = 0
    for component in STEDGEAI_RUNTIME_COMPONENTS:
        source_component = source_root / component
        destination_component = destination_root / component
        shutil.copytree(source_component, destination_component, dirs_exist_ok=True)
        source_files = sorted(path for path in source_component.rglob("*") if path.is_file())
        component_counts[component] = len(source_files)
        for source_file in source_files:
            relative_path = source_file.relative_to(source_component)
            destination_file = destination_component / relative_path
            if not destination_file.is_file() or sha256_file(destination_file) != sha256_file(
                source_file
            ):
                raise ValueError(f"Runtime synchronization verification failed: {relative_path}.")
            verified_files += 1

    for filename in ("APACHE-2.0.txt", "LICENSE.txt"):
        source_file = source_root / filename
        if source_file.is_file():
            shutil.copy2(source_file, destination_root / filename)

    version_header = destination_root / "Npu/ll_aton/ll_aton_version.h"
    version_name = _parse_ll_aton_version(version_header)
    network_runtime = resolve_network_runtime_library(application_directory)
    if version_name is None or network_runtime is None:
        raise ValueError("Synchronized runtime version or CM55 GCC library could not be resolved.")

    output_directory.mkdir(parents=True, exist_ok=True)
    manifest_path = output_directory / "runtime-sync.json"
    manifest_path.write_text(
        json.dumps(
            {
                "core_directory": str(core_directory),
                "source": str(source_root),
                "destination": str(destination_root),
                "ll_aton_version": version_name,
                "network_runtime_library": network_runtime.name,
                "network_runtime_sha256": sha256_file(network_runtime),
                "version_header_sha256": sha256_file(version_header),
                "verified_files": verified_files,
                "component_file_counts": component_counts,
                "strategy": "overlay-and-hash-verify",
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return manifest_path


def resolve_network_runtime_library(application_directory: Path) -> Path | None:
    """Return the newest NetworkRuntime CM55 GCC archive in an official checkout."""

    library_directory = (
        application_directory.resolve().parent.parent
        / "Middlewares/stedgeai-lib/Lib/GCC/ARMCortexM55"
    )
    candidates: list[tuple[int, Path]] = []
    for path in library_directory.glob("NetworkRuntime*_CM55_GCC.a"):
        match = re.fullmatch(r"NetworkRuntime(\d+)_CM55_GCC\.a", path.name)
        if match:
            candidates.append((int(match.group(1)), path))
    return max(candidates, default=(0, None), key=lambda item: item[0])[1]


def _parse_ll_aton_version(version_header: Path) -> str | None:
    if not version_header.is_file():
        return None
    match = re.search(
        r'^#define\s+LL_ATON_VERSION_NAME\s+"(?P<version>[^"]+)"',
        version_header.read_text(encoding="utf-8"),
        re.MULTILINE,
    )
    return match.group("version") if match else None


def resolve_programmer() -> Path | None:
    configured = os.getenv("STM32_PRG_PATH")
    candidates = []
    if configured:
        candidates.append(Path(configured) / "STM32_Programmer_CLI.exe")
    located = shutil.which("STM32_Programmer_CLI")
    if located:
        candidates.append(Path(located))
    candidates.append(
        Path(
            "C:/Program Files/STMicroelectronics/STM32Cube/"
            "STM32CubeProgrammer/bin/STM32_Programmer_CLI.exe"
        )
    )
    return next((path.resolve() for path in candidates if path.is_file()), None)


def resolve_external_loader(programmer: Path | None = None) -> Path | None:
    executable = programmer or resolve_programmer()
    if executable is None:
        return None
    path = executable.parent / "ExternalLoader/MX25UM51245G_STM32N6570-NUCLEO.stldr"
    return path.resolve() if path.is_file() else None


def resolve_make() -> Path | None:
    return _resolve_cubeide_tool("externaltools.make.win32", "make.exe")


def resolve_gcc_directory() -> Path | None:
    executable = _resolve_cubeide_tool("externaltools.gnu-tools-for-stm32", "arm-none-eabi-gcc.exe")
    return executable.parent if executable is not None else None


def resolve_signing_tool() -> Path | None:
    return _resolve_cubeide_tool("externaltools.cubeprogrammer.win32", "STM32_SigningTool_CLI.exe")


def resolve_objcopy() -> Path | None:
    return _resolve_cubeide_tool("externaltools.gnu-tools-for-stm32", "arm-none-eabi-objcopy.exe")


def _resolve_cubeide_tool(plugin_fragment: str, filename: str) -> Path | None:
    candidates: list[Path] = []
    for root in (
        Path("C:/ST/STM32CubeIDE_2.2.0"),
        Path("C:/ST/STM32CubeIDE_2.0.0"),
        Path("C:/ST/STM32CubeIDE_1.19.0"),
    ):
        plugin_root = root / "STM32CubeIDE/plugins"
        if plugin_root.is_dir():
            candidates.extend(plugin_root.glob(f"*{plugin_fragment}*/tools/bin/{filename}"))
    located = shutil.which(filename)
    if located:
        candidates.append(Path(located))
    return next((path.resolve() for path in candidates if path.is_file()), None)


def _capture_serial(port: str, *, baud_rate: int, duration_seconds: float) -> list[str]:
    import serial  # type: ignore[import-untyped]

    lines: list[str] = []
    deadline = time.monotonic() + duration_seconds
    with serial.Serial(port, baud_rate, timeout=0.25) as connection:
        while time.monotonic() < deadline:
            raw = connection.readline()
            if raw:
                lines.append(raw.decode("utf-8", errors="replace").rstrip())
    return lines


def _validate_program_request(
    config: NucleoDeploymentConfig,
    firmware: list[FirmwareImage],
) -> str | None:
    if config.expected_board != EXPECTED_BOARD:
        return f"Unsupported board: {config.expected_board}."
    if config.boot_mode != "development":
        return "Programming requires boot_mode=development."
    if not firmware:
        return "At least one firmware image is required."
    for image in firmware:
        if not image.path.is_file():
            return f"Firmware image does not exist: {image.path}."
        if image.path.suffix.lower() not in {".hex", ".bin"}:
            return f"Firmware must be .hex or .bin: {image.path}."
        if image.path.suffix.lower() == ".bin" and image.address is None:
            return f"Binary firmware requires an explicit address: {image.path}."
        if image.address is not None and re.fullmatch(r"0x[0-9a-fA-F]{8}", image.address) is None:
            return f"Invalid firmware address: {image.address}."
    return None


def _parse_board(stdout: str) -> str | None:
    match = re.search(r"^Board\s*:\s*(.+?)\s*$", stdout, re.MULTILINE)
    return match.group(1).strip() if match else None


def _probe_error(
    outcome: CommandOutcome,
    probed_board: str | None,
    expected_board: str,
) -> str | None:
    if outcome.exit_code not in {None, 0} or outcome.timed_out:
        return first_error(outcome) or f"Board probe failed with exit code {outcome.exit_code}."
    if probed_board != expected_board:
        return f"Expected {expected_board}, detected {probed_board or 'unknown'}."
    return None


def _stage(
    name: DeploymentStageName,
    outcome: CommandOutcome,
    started_at: datetime,
    artifacts: list[ArtifactRef],
    *,
    succeeded: bool,
    error_override: str | None = None,
) -> DeploymentStage:
    return DeploymentStage(
        stage=name,
        status=StageStatus.SUCCEEDED if succeeded else StageStatus.FAILED,
        started_at=started_at,
        ended_at=datetime.now(UTC),
        duration_ms=outcome.duration_ms,
        command=list(outcome.command),
        exit_code=outcome.exit_code,
        first_error=None if succeeded else error_override or first_error(outcome),
        artifacts=artifacts,
    )


def _file_artifact(path: Path, kind: ArtifactKind, description: str) -> ArtifactRef:
    return ArtifactRef(
        kind=kind,
        path=str(path),
        sha256=sha256_file(path),
        size_bytes=path.stat().st_size,
        description=description,
    )


def _optional_model_artifact(path: Path | None) -> ArtifactRef | None:
    if path is None:
        return None
    return _file_artifact(path, ArtifactKind.INPUT_MODEL, "Model associated with deployment")


def _failed_result(config: NucleoDeploymentConfig, reason: str) -> DeploymentResult:
    return DeploymentResult(
        status=StageStatus.FAILED,
        application=config.application,
        board=config.expected_board,
        serial_port=config.serial_port,
        boot_mode=config.boot_mode,
        reason=reason,
    )


def _write_result(result: DeploymentResult, output_directory: Path) -> DeploymentResult:
    output_directory.mkdir(parents=True, exist_ok=True)
    (output_directory / "deployment-result.json").write_text(
        result.model_dump_json(indent=2) + "\n",
        encoding="utf-8",
    )
    return result

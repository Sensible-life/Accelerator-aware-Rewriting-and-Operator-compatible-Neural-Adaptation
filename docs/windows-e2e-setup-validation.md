# Windows E2E setup and validation log

이 문서는 ARONA를 Windows 외부 환경에서 설치하고, ST NUCLEO-N657X0-Q 보드에 MobileNet/YOLO
모델을 배포·검증하기 위해 실제로 시도했던 설치, 환경변수, 실행 명령, 오류와 해결책을 한 곳에
모은 기록이다.

기준 환경:

- OS: Windows PowerShell
- Repository: `C:\Users\ChoSungwon\Desktop\dev\ARONA`
- Board: `NUCLEO-N657X0-Q`
- Serial port: `COM3`
- Programmer: STM32CubeProgrammer CLI
- Compiler/runtime: ST Edge AI Core `v4.0.1-20581`
- Toolchain: STM32CubeIDE `2.2.0` bundled Make/GNU Arm tools/signing tool

## 1. Repository path 정리

처음 repository 경로가 너무 길어 Windows checkout/build에서 문제가 났다.

기존 긴 경로:

```text
C:\Users\ChoSungwon\Desktop\dev\Accelerator-aware-Rewriting-and-Operator-compatible-Neural-Adaptation
```

사용한 짧은 경로:

```text
C:\Users\ChoSungwon\Desktop\dev\ARONA
```

이름을 바꾼 뒤에는 새 터미널에서 repository root로 이동한다.

```powershell
cd C:\Users\ChoSungwon\Desktop\dev\ARONA
```

Windows에서 vendor repository를 clone할 때 `Filename too long`이 나면 Git long paths를 켠다.

```powershell
git config --global core.longpaths true
```

그래도 경로가 긴 dependency tree에서는 repository 자체를 짧은 경로에 두는 것이 가장 확실했다.

## 2. Python/ARONA 실행 확인

ARONA는 `uv` 환경에서 실행했다.

```powershell
uv sync
uv run arona --help
uv run arona discover
```

최종 확인된 discovery 예시:

```text
Target environment
  backend: stedgeai
  status: available
  board: NUCLEO-N657X0-Q
  accelerator: ST Neural-ART
  compiler: stedgeai ST Edge AI Core v4.0.1-20581 7ed50de05
```

전체 테스트:

```powershell
uv run pytest
```

검증 결과:

```text
50 passed, 1 skipped
```

## 3. ST-LINK와 serial port 확인

Windows 장치 목록에서 ST-LINK와 VCP를 분리해서 확인했다.

```powershell
Get-PnpDevice -PresentOnly |
  Where-Object { $_.FriendlyName -match 'ST-?LINK|STLink|STMicro|J-?Link|USB Serial' } |
  Format-Table Status, Class, FriendlyName, InstanceId -AutoSize

Get-CimInstance Win32_SerialPort |
  Select-Object DeviceID, Name, PNPDeviceID
```

확인된 값:

```text
ST-Link Debug USB
USB\VID_0483&PID_3754&MI_00\...

COM3
USB 직렬 장치(COM3)
USB\VID_0483&PID_3754&MI_01\...
```

STM32CubeProgrammer CLI로 보드 probe:

```powershell
& "C:\Program Files\STMicroelectronics\STM32Cube\STM32CubeProgrammer\bin\STM32_Programmer_CLI.exe" `
  -c port=SWD mode=UR
```

정상 출력 핵심:

```text
Board       : NUCLEO-N657X0-Q
Voltage     : 3.26V
Device ID   : 0x486
Device name : ST32N657
Device CPU  : Cortex-M55
```

## 4. ST Edge AI Core 4.0 설정

처음에는 3.0이 잡혔고, 4.0 경로로 바꿨다. 최종 사용 경로는 다음과 같다.

```powershell
$env:ARONA_STEDGEAI_PATH = "C:\ST\STEdgeAI2\4.0\Utilities\windows\stedgeai.exe"
$env:STEDGEAI_CORE_DIR = "C:\ST\STEdgeAI2\4.0"
$env:Path = "C:\ST\STEdgeAI2\4.0\Utilities\windows;" + $env:Path
```

확인:

```powershell
stedgeai --version
```

정상 출력:

```text
ST Edge AI Core v4.0.1-20581 7ed50de05
```

주의: 3.0 경로를 단순 복사/이름 변경한 상태에서는 다음 오류가 났다.

```text
ModuleNotFoundError: No module named 'utilities.c_info_data'
```

해결은 올바른 4.0 설치/압축 해제 경로를 사용하고, `ARONA_STEDGEAI_PATH`,
`STEDGEAI_CORE_DIR`, `Path`를 모두 같은 Core로 맞추는 것이다.

## 5. STM32CubeProgrammer 설치 확인

처음에는 `STM32_Programmer_CLI`가 PATH에서 안 잡혔다.

```powershell
Get-Command STM32_Programmer_CLI -ErrorAction SilentlyContinue
Get-ChildItem "C:\Program Files\STMicroelectronics" -Recurse -Filter STM32_Programmer_CLI.exe -ErrorAction SilentlyContinue
```

실제 사용 경로:

```text
C:\Program Files\STMicroelectronics\STM32Cube\STM32CubeProgrammer\bin\STM32_Programmer_CLI.exe
```

필요하면 PATH에 추가한다.

```powershell
$env:Path = "C:\Program Files\STMicroelectronics\STM32Cube\STM32CubeProgrammer\bin;" + $env:Path
```

## 6. STM32CubeIDE build tools 확인

처음 build에서 다음 오류가 났다.

```text
reason: Missing build tools: make, signing tool.
reason: Missing build tools: GCC.
```

STM32CubeIDE 2.2.0에 포함된 도구를 사용했다.

대표 경로:

```text
C:\ST\STM32CubeIDE_2.2.0\STM32CubeIDE\plugins\
```

PowerShell에서 도구를 찾아 PATH에 추가한다.

```powershell
$makePath = Get-ChildItem "C:\ST\STM32CubeIDE_2.2.0\STM32CubeIDE\plugins" `
  -Recurse -Filter make.exe |
  Select-Object -First 1

$gccPath = Get-ChildItem "C:\ST\STM32CubeIDE_2.2.0\STM32CubeIDE\plugins" `
  -Recurse -Filter arm-none-eabi-gcc.exe |
  Select-Object -First 1

$signPath = Get-ChildItem "C:\ST\STM32CubeIDE_2.2.0\STM32CubeIDE\plugins" `
  -Recurse -Filter STM32_SigningTool_CLI.exe |
  Select-Object -First 1

$objcopyPath = Get-ChildItem "C:\ST\STM32CubeIDE_2.2.0\STM32CubeIDE\plugins" `
  -Recurse -Filter arm-none-eabi-objcopy.exe |
  Select-Object -First 1

$env:Path = "$($makePath.Directory.FullName);$($gccPath.Directory.FullName);$($signPath.Directory.FullName);$($objcopyPath.Directory.FullName);" + $env:Path
```

확인:

```powershell
Get-Command make.exe
Get-Command arm-none-eabi-gcc.exe
Get-Command arm-none-eabi-objcopy.exe
Get-Command STM32_SigningTool_CLI.exe
```

## 7. Vendor repository 준비

필요한 vendor checkout:

```text
outputs/vendor/STM32N6-GettingStarted-ImageClassification
outputs/vendor/STM32N6-GettingStarted-ObjectDetection
```

존재 확인:

```powershell
Test-Path outputs/vendor/STM32N6-GettingStarted-ImageClassification/Application/NUCLEO-N657X0-Q
Test-Path outputs/vendor/STM32N6-GettingStarted-ImageClassification/Model
Test-Path outputs/vendor/STM32N6-GettingStarted-ImageClassification/FSBL/ai_fsbl.hex

Test-Path outputs/vendor/STM32N6-GettingStarted-ObjectDetection/Application/NUCLEO-N657X0-Q
Test-Path outputs/vendor/STM32N6-GettingStarted-ObjectDetection/Model
Test-Path outputs/vendor/STM32N6-GettingStarted-ObjectDetection/FSBL/ai_fsbl.hex
```

잘못된 짧은 복사 경로를 넘기면 다음 오류가 난다.

```text
reason: NUCLEO Neural-ART profile is missing: ...\user_neuralart_NUCLEO-N657X0-Q.json
```

해결: `--model-support-directory`에는 vendor repository의 `Model` directory를 넘긴다.

## 8. 모델 파일 확인

사용한 모델:

```powershell
Get-ChildItem models\downloads
```

확인된 파일:

```text
mobilenetv2_a035_128_food101_qdq.onnx
yolo26n_256_coco_person_qdq_int8.onnx
```

## 9. MobileNet step-by-step deployment

### 9.1 Generate

```powershell
uv run arona deployment generate `
  --application image_classification `
  --model-support-directory outputs/vendor/STM32N6-GettingStarted-ImageClassification/Model `
  models/downloads/mobilenetv2_a035_128_food101_qdq.onnx `
  -o outputs/deployment/image-classification/generated
```

성공:

```text
status: succeeded
reason: Model code and external-flash network data generated.
```

### 9.2 Runtime sync

```powershell
uv run arona deployment sync-runtime `
  --core-directory C:\ST\STEdgeAI2\4.0 `
  outputs/vendor/STM32N6-GettingStarted-ImageClassification/Application/NUCLEO-N657X0-Q `
  -o outputs/deployment/image-classification/runtime-sync
```

성공 산출물:

```text
outputs/deployment/image-classification/runtime-sync/runtime-sync.json
```

### 9.3 Instrument/configure/fixed-input

```powershell
uv run arona deployment instrument `
  --application image_classification `
  outputs/vendor/STM32N6-GettingStarted-ImageClassification/Application/NUCLEO-N657X0-Q

uv run arona deployment configure `
  --application image_classification `
  outputs/vendor/STM32N6-GettingStarted-ImageClassification/Application/NUCLEO-N657X0-Q

uv run arona deployment fixed-input `
  --application image_classification `
  outputs/vendor/STM32N6-GettingStarted-ImageClassification/Application/NUCLEO-N657X0-Q
```

`fixed-input`은 카메라 없이도 실제 inference 경로를 반복 검증하기 위해 사용했다.

### 9.4 Build

```powershell
uv run arona deployment build `
  --application image_classification `
  --jobs 8 `
  --build-top build-arona-mobilenetv2-core401 `
  --model-directory outputs/deployment/image-classification/generated/model-files `
  outputs/vendor/STM32N6-GettingStarted-ImageClassification/Application/NUCLEO-N657X0-Q `
  -o outputs/deployment/image-classification/build
```

성공:

```text
status: succeeded
[succeeded] link
reason: Official application built and signed; board programming was not requested.
```

### 9.5 Program

보드는 development boot 상태에서 programming한다.

```text
JP1: position 1
JP2: position 2
```

대표 명령:

```powershell
uv run arona deployment program `
  --application image_classification `
  --model models/downloads/mobilenetv2_a035_128_food101_qdq.onnx `
  outputs/vendor/STM32N6-GettingStarted-ImageClassification/FSBL/ai_fsbl.hex `
  outputs/vendor/STM32N6-GettingStarted-ImageClassification/Application/NUCLEO-N657X0-Q/build-arona-mobilenetv2-core401/Application/NUCLEO-N657X0-Q/Project_sign.hex `
  outputs/deployment/image-classification/generated/model-files/network_data.hex `
  -o outputs/deployment/image-classification/program
```

성공 후:

```text
Switch to flash boot, power-cycle, then run serial validation.
```

flash boot:

```text
JP1: position 1
JP2: position 1
```

### 9.6 Validate

```powershell
uv run arona deployment validate `
  --application image_classification `
  --serial-port COM3 `
  --inference-count 5 `
  --expected-model-name mobilenetv2_a035_128_food101_qdq_OE_3_3_1 `
  --expected-input-fnv1a 0xfbe51dc5 `
  -o outputs/deployment/image-classification/fixed-input-validate
```

성공:

```text
status: succeeded
[succeeded] inference
[succeeded] validation
reason: Observed 2049 successful inference records.
```

## 10. YOLO step-by-step deployment

### 10.1 Generate

```powershell
uv run arona deployment generate `
  --application object_detection `
  --model-support-directory outputs/vendor/STM32N6-GettingStarted-ObjectDetection/Model `
  models/downloads/yolo26n_256_coco_person_qdq_int8.onnx `
  -o outputs/deployment/object-detection/generated
```

### 10.2 Runtime sync

```powershell
uv run arona deployment sync-runtime `
  --core-directory C:\ST\STEdgeAI2\4.0 `
  outputs/vendor/STM32N6-GettingStarted-ObjectDetection/Application/NUCLEO-N657X0-Q `
  -o outputs/deployment/object-detection/runtime-sync
```

### 10.3 Fixed input

```powershell
uv run arona deployment fixed-input `
  --application object_detection `
  outputs/vendor/STM32N6-GettingStarted-ObjectDetection/Application/NUCLEO-N657X0-Q
```

### 10.4 Build

```powershell
uv run arona deployment build `
  --application object_detection `
  --jobs 8 `
  --build-top build-yolo-core401 `
  --model-directory outputs/deployment/object-detection/generated/model-files `
  outputs/vendor/STM32N6-GettingStarted-ObjectDetection/Application/NUCLEO-N657X0-Q `
  -o outputs/deployment/object-detection/build
```

만난 오류:

```text
../../../../deployment/object-detection/generated/model-files/network.c:59:4:
error: #error "Possible mismatch in ll_aton library used"
```

원인:

- generated `network.c`가 ST Edge AI Core 3.0 기반 산출물이었다.
- application runtime은 4.0.1로 sync되어 있었다.
- model generation Core와 runtime Core가 달라서 `ll_aton` mismatch가 발생했다.

해결:

1. `ARONA_STEDGEAI_PATH`, `STEDGEAI_CORE_DIR`, `Path`를 모두 `C:\ST\STEdgeAI2\4.0`으로 맞춘다.
2. YOLO generated model-files를 4.0.1로 다시 생성한다.
3. 새 generated directory를 `--model-directory`로 넘겨 clean build한다.

### 10.5 Validate

```powershell
uv run arona deployment validate `
  --application object_detection `
  --serial-port COM3 `
  --inference-count 5 `
  --expected-input-fnv1a 0x6c3e9dc5 `
  -o outputs/deployment/object-detection/fixed-input-validate
```

성공:

```text
status: succeeded
[succeeded] inference
[succeeded] validation
reason: Observed 927 successful inference records.
```

측정 기록:

```text
latency mean: 20.939 ms
```

## 11. Optimize smoke test with fixture logs

실제 보드 배포 전에 fixture compiler log로 optimize pipeline을 확인했다.

```powershell
uv run arona optimize `
  outputs/demo/mobilenetv2_a035_128_food101_terminal_argmax.onnx `
  --target stedgeai `
  --compiler-log tests/fixtures/backends/stedgeai/conmamba_fallback/compiler.log `
  --candidate-compiler-log tests/fixtures/backends/stedgeai/conmamba_xip_101/compiler.log `
  --output-directory outputs/demo-runs
```

핵심 결과:

```text
Rewrites
  [applied] terminal_argmax_externalization.v1; validation=passed

Decision
  selected: optimized
  accepted: True
```

baseline은 HyperRAM pool 때문에 NUCLEO board profile에서 infeasible했고, optimized candidate는
feasible했다.

## 12. One-shot optimize --deploy

최종 MVP 한방 경로는 `arona optimize --deploy`로 검증했다.

```powershell
uv run arona optimize `
  outputs/demo/mobilenetv2_a035_128_food101_terminal_argmax.onnx `
  --target stedgeai `
  --validation-input inputs/demo `
  --deploy `
  --deployment-application image_classification `
  --application-directory outputs/vendor/STM32N6-GettingStarted-ImageClassification/Application/NUCLEO-N657X0-Q `
  --model-support-directory outputs/vendor/STM32N6-GettingStarted-ImageClassification/Model `
  --fsbl outputs/vendor/STM32N6-GettingStarted-ImageClassification/FSBL/ai_fsbl.hex `
  --serial-port COM3 `
  --inference-count 5 `
  --expected-input-fnv1a 0xfbe51dc5 `
  --build-top build-optimize-mobile `
  --output-directory outputs/demo-runs
```

도중 CLI가 다음을 안내하면:

```text
Programming completed. Move JP2 to position 1 (flash boot), power-cycle the board,
and wait for COM3 to reconnect.
Continue with UART inference validation? [y/N]:
```

작업:

1. 보드 전원을 끈다.
2. JP2를 flash boot position 1로 옮긴다.
3. 보드 전원을 다시 연결한다.
4. `COM3`가 다시 잡히면 `y`를 입력한다.

최종 성공 결과:

```text
Board deployment
  application: image_classification
  board: NUCLEO-N657X0-Q
  status: succeeded
  serial port: COM3
  boot mode: flash
  reason: Observed 2280 successful inference records.
  observations: 2280/2280 succeeded
  latency_ms: min=2.000 mean=2.644 max=3.000
```

산출물:

```text
outputs/demo-runs/20260824T001942Z-optimize
```

## 13. ARONA doctor and CLI welcome scene

추가한 CLI 점검 명령:

```powershell
uv run arona doctor --serial-port COM3
```

유니코드 welcome scene과 컬러를 강제로 켜려면:

```powershell
$env:ARONA_UNICODE = "1"
$env:ARONA_COLOR = "1"
uv run arona doctor --serial-port COM3
```

`ARONA_COLOR=1`은 상위 환경에 `NO_COLOR`가 설정돼 있어도 ARONA의 컬러 출력을 강제로
활성화한다. 색상만 끄고 유니코드 장면은 유지하려면:

```powershell
Remove-Item Env:\ARONA_COLOR -ErrorAction SilentlyContinue
$env:NO_COLOR = "1"
uv run arona doctor --serial-port COM3
```

구형 콘솔에서 ASCII 장면까지 강제하려면:

```powershell
$env:ARONA_PLAIN_BANNER = "1"
uv run arona doctor --serial-port COM3
```

`doctor`가 확인하는 항목:

- ST Edge AI Core
- STM32CubeProgrammer
- NUCLEO external loader
- make
- Arm GCC
- Arm objcopy
- STM32 signing tool
- ST-LINK serial port

serial port 자동 탐지가 실패해도 `--serial-port COM3`로 명시할 수 있다.

### 공통 CLI UX

모든 상위 명령과 deployment 하위 명령은 동일한 출력 구조를 사용한다.

- `ARONA + 명령명` 헤더와 한 줄 목적 설명
- 정렬된 `key: value` 정보
- `1/4` 형태의 단계 번호와 `✓`/`!`/`✗` 상태
- 사용자 조작이 필요한 경우 경고 상자
- 성공·실패 이유와 산출물 경로를 표시하는 결과 상자
- 긴 경로와 문장은 현재 터미널 너비에 맞춰 줄바꿈

적용 명령은 `version`, `discover`, `doctor`, `analyze`, `optimize`, `schema export`와
`deployment instrument/fixed-input/configure/build/sync-runtime/generate/program/backup/validate`다.

### 화살표 키 인터랙티브 런처

인자 없이 실행하면 초보자용 작업 런처가 열린다.

```powershell
uv run arona
```

런처는 다음 동작을 제공한다.

1. 첫 화면에서 현재 모델, 보드, 환경과 전체 배포 workflow 상태를 확인한다.
2. 위·아래 화살표로 `doctor`, `discover`, `analyze`, `optimize`, `optimize --deploy`,
   `deployment validate`, 전체 도움말 중 하나를 직접 선택한다.
3. 모델이 필요한 작업은 경로 자동완성 입력을 제공한다.
4. 변경이나 배포가 발생하는 작업은 생성된 실제 CLI 명령을 먼저 보여준다.
5. 실행 중에는 `Inspect → Analyze → Optimize → Deploy → Validate` 트래커에서 완료, 실행 중,
   대기 상태를 구분한다.
6. 명령 완료 후 결과 보고서에서 모델, 출력 경로, 소요 시간, 종료 코드와 추천 다음 행동을
   확인하고 런처 복귀 또는 종료를 선택한다.

직접 명령 실행 방식은 변경하지 않았으며, CI나 redirect처럼 TTY가 아닌 환경에서 `arona`만
실행하면 일반 도움말로 fallback한다. 런처를 명시적으로 열려면 다음을 사용한다.

```powershell
uv run arona interactive
```

## 14. 자주 만난 오류와 해결

### uv trampoline failed to canonicalize script path

repository 폴더 이름을 바꾼 뒤 기존 venv/script가 예전 경로를 물고 있을 때 발생했다.

해결:

```powershell
Remove-Item -Recurse -Force .venv
uv sync
uv run pytest
```

### Filename too long

vendor repository checkout 중 CMSIS/DSP 예제 경로가 길어서 발생했다.

해결:

```powershell
git config --global core.longpaths true
```

그리고 repository root를 짧은 경로로 바꿨다.

```text
C:\Users\ChoSungwon\Desktop\dev\ARONA
```

### STEdgeAI Core or Arm objcopy is missing

`generate`에서 `stedgeai` 또는 `arm-none-eabi-objcopy.exe`를 찾지 못한 상태다.

해결:

- `ARONA_STEDGEAI_PATH`와 `STEDGEAI_CORE_DIR`을 4.0으로 설정한다.
- STM32CubeIDE GNU tools `tools/bin`을 PATH에 추가한다.

### Missing build tools: make, signing tool, GCC

`build`에서 CubeIDE bundled tools를 못 찾은 상태다.

해결:

- STM32CubeIDE 2.2.0 설치 확인
- `make.exe`, `arm-none-eabi-gcc.exe`, `STM32_SigningTool_CLI.exe`가 있는 directory를 PATH에 추가

### Possible mismatch in ll_aton library used

model code generation에 사용한 ST Edge AI Core와 application runtime library가 다를 때 발생했다.

해결:

```powershell
$env:ARONA_STEDGEAI_PATH = "C:\ST\STEdgeAI2\4.0\Utilities\windows\stedgeai.exe"
$env:STEDGEAI_CORE_DIR = "C:\ST\STEdgeAI2\4.0"
$env:Path = "C:\ST\STEdgeAI2\4.0\Utilities\windows;" + $env:Path
```

그 다음:

1. `deployment sync-runtime` 재실행
2. `deployment generate` 재실행
3. 새 `--build-top`으로 clean build

### compile 성공 != board 실행 성공

이번 검증에서 실제로 확인한 구분:

- `generate` 성공: model code/network data 생성
- `build` 성공: application link/sign 성공
- `program` 성공: external flash에 firmware write 성공
- `validate` 성공: flash boot 후 UART inference record 확인

따라서 compile/generate/build 성공만으로 target validation 성공이라고 기록하지 않는다.

## 15. 최종 검증 요약

| 항목 | 결과 |
|---|---|
| `uv run arona discover` | ST Edge AI Core 4.0.1, NUCLEO-N657X0-Q 확인 |
| MobileNet step-by-step validation | 2049 successful inference records |
| YOLO step-by-step validation | 927 successful inference records |
| `arona optimize --deploy` one-shot | 2280/2280 successful inference records |
| MobileNet one-shot latency | min 2.000 ms, mean 2.644 ms, max 3.000 ms |
| `uv run pytest` | 50 passed, 1 skipped |
| `uv run ruff check src tests` | All checks passed |

## 16. 다음 PC에서 재현할 최소 순서

1. Repository를 짧은 경로에 둔다.
2. `uv sync`를 실행한다.
3. STM32CubeProgrammer CLI가 설치됐는지 확인한다.
4. ST Edge AI Core 4.0.1 경로를 환경변수로 잡는다.
5. STM32CubeIDE 2.2.0 bundled Make/GCC/objcopy/signing tool을 PATH에 추가한다.
6. ST-LINK와 COM port를 확인한다.
7. vendor repositories가 `outputs/vendor` 아래에 있는지 확인한다.
8. `uv run arona doctor --serial-port COM3`를 실행한다.
9. `deployment generate -> sync-runtime -> instrument/configure/fixed-input -> build -> program -> validate` 순서로 모델 하나를 검증한다.
10. 마지막으로 `arona optimize --deploy` 한방 경로를 실행한다.

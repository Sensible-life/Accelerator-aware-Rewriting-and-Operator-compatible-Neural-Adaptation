# NUCLEO-N657X0-Q 터미널 연결·부트·배포·복구 매뉴얼

이 문서는 NUCLEO-N657X0-Q를 Windows 또는 macOS 개발 PC에 연결하고, VS Code의 통합
터미널이나 일반 터미널에서 연결 상태를 확인하며, STM32CubeIDE와 STM32CubeProgrammer GUI
없이 ARONA 또는 생성된 STM32N6 firmware를 실행하기 위한 절차를 설명한다. 사람뿐 아니라 다른
코딩 에이전트가 그대로 읽고 진단할 수 있도록 관찰값, 판정 기준, 금지할 추측을 함께 기록한다.

검증 기준 환경:

- Board: `NUCLEO-N657X0-Q`, board reference MB1940, target `STM32N657X0H3Q`
- Accelerator: ST Neural-ART
- Model compiler/runtime: STEdgeAI Core `4.0.1`
- Debug paths: onboard `STLINK-V3EC` 또는 CN1에 연결한 external SEGGER J-Link/Flasher
- Serial telemetry: `115200 8-N-1`, flow control 없음
- Repository root: 이 문서의 상위 디렉터리

> [!CAUTION]
> JP1/JP2는 전원을 제거한 상태에서 바꾸고 다시 전원을 연결한다. OTP/fuse programming,
> readout protection 변경, chip erase, 외부 flash 전체 erase는 이 문서의 범위가 아니다. 모델을
> 바꾸기 위해 OTP를 건드릴 필요는 없다.

## 1. 먼저 알아야 할 핵심 사실

### 1.1 포트 이름을 혼동하지 않는다

최신 ST 공식 보드 매뉴얼 UM3417 기준 포트의 역할은 다음과 같다.

| 부품 | 역할 | 이 작업에서의 사용 |
|---|---|---|
| `CN10` | onboard STLINK-V3EC USB Type-C, 보드 전원, SWD/JTAG, VCP | 기본 전원 및 ST-LINK/VCP 연결 |
| `CN8` | target MCU의 user USB Type-C | UVC 또는 application USB; ST-LINK가 아님 |
| `CN1` | MIPI20 external debug connector | external J-Link/Flasher 연결 |
| `CN9` | 5 V 전원원 선택 점퍼 | CN10 전원을 쓸 때 `[1-2]` |
| `JP1` | BOOT0 | flash/development 작업에서 `[1-2]`, logic 0 |
| `JP2` | BOOT1 | development와 flash boot 전환 |
| `B2` | target reset | 설정 후 reset이 필요할 때 사용 |
| `JP3` | ST-LINK reset | 일반적인 target reset 용도가 아님 |

로컬 ST Getting Started README 일부에는 onboard ST-LINK 포트를 `CN9`라고 적은 부분이 있다.
그러나 MB1940 최신 보드 매뉴얼에서 **USB ST-LINK 포트는 CN10이고 CN9는 전원 선택
점퍼**다. 실제 PCB silkscreen과 UM3417을 우선한다.

### 1.2 STM32N6에는 code용 internal flash가 없다

전원을 껐다 켠 뒤에도 실행하려면 외부 Octo-SPI flash에 다음 세 종류를 함께 배치해야 한다.

| 구성요소 | 기본 주소 | 의미 |
|---|---:|---|
| FSBL | `0x70000000` | signed application을 외부 flash에서 SRAM으로 적재하는 boot loader |
| Signed application | `0x70100000` | model schedule/code와 application을 포함하는 실행 image |
| Network data | `0x70380000` | STEdgeAI가 만든 weights/constants |

Intel HEX 파일에는 주소가 들어 있으므로 주소를 다시 주지 않는다. `.bin` 파일을 사용할 때만
위 주소를 명시한다.

### 1.3 ONNX를 그대로 보드에 복사할 수 없다

NUCLEO-N657X0-Q firmware에는 ONNX Runtime이 없다. ONNX 하나를 flash에 복사하는 것은 모델
배포가 아니다. 새 ONNX는 다음 과정을 거쳐야 한다.

```text
ONNX
  -> STEdgeAI 4.0.1 generate
  -> network.c / stai_network.c / runtime metadata
  -> network_atonbuf.xSPI2.raw
  -> network_data.hex
  -> application compile/link
  -> persistent boot이면 application signing
  -> FSBL + application + network_data programming
```

`network_data.hex`와 `Project_sign.hex`는 같은 STEdgeAI generation 결과에서 만들어진 한 쌍이어야
한다. 임의 모델의 weights만 바꾸고 예전 application을 그대로 쓰지 않는다.

## 2. JP1/JP2 boot mode

ST 공식 boot truth table은 다음과 같다.

| BOOT0 | BOOT1 | Boot source |
|---:|---:|---|
| don't care | 1 | Development boot |
| 0 | 0 | Flash boot |
| 1 | 0 | Serial boot |

ARONA 작업에서는 serial boot를 사용하지 않는다. 물리 설정은 다음 두 가지만 사용한다.

### Development boot: build를 RAM에서 실행하거나 외부 flash를 program할 때

- `JP1 BOOT0`: `[1-2]`, position 1, logic 0
- `JP2 BOOT1`: `[2-3]`, position 2, logic 1
- 전원을 완전히 제거한 뒤 설정하고 CN10을 다시 연결한다.

### Flash boot: 외부 flash에 적재된 application을 실행할 때

- `JP1 BOOT0`: `[1-2]`, position 1, logic 0
- `JP2 BOOT1`: `[1-2]`, position 1, logic 0
- programming을 마친 뒤 전원을 제거하고 JP2를 옮긴 다음 다시 연결한다.

즉, 일반적인 ARONA 순서는 다음과 같다.

```text
전원 OFF
  -> JP1 position 1 + JP2 position 2
  -> 전원 ON
  -> program
  -> 전원 OFF
  -> JP2만 position 1로 이동
  -> 전원 ON
  -> UART/inference validate
```

> [!IMPORTANT]
> `DEV_USB_COMM_ERR`는 우선 host PC와 ST-LINK probe 사이의 USB 통신 오류다. JP2는 target의
> boot source를 고르므로, ST-LINK 자체가 USB로 정상 enumerate되지 않은 상태에서는 JP2를 계속
> 바꿔도 문제를 해결하지 못한다.

로컬에서 확인할 수 있는 ST 제공 사진:

- [Development boot 사진](../outputs/vendor/STM32N6-GettingStarted-ImageClassification/_htmresc/NUCLEO-N657X0-Q_Dev_mode.png)
- [Flash boot 사진](../outputs/vendor/STM32N6-GettingStarted-ImageClassification/_htmresc/NUCLEO-N657X0-Q_Boot_from_flash.png)

## 3. 물리 연결의 최소 정상 상태

### Onboard ST-LINK만 사용할 때

1. CN9 power selector를 `[1-2]`로 둔다.
2. 데이터 전송이 되는 짧고 품질 좋은 USB-C 케이블을 CN10에 연결한다.
3. 가능하면 USB hub, dock, USB-A 변환 젠더를 제거하고 PC에 직접 연결한다.
4. shield가 연결돼 있다면 먼저 제거해 기본 보드만 검사한다.
5. 정상 USB enumeration 뒤 `LD1` 5V power LED가 켜지는지 확인한다.
6. `LD4` ST-LINK power status와 `LD9` ST-LINK COM 상태를 기록한다.

LED 판정:

| LED | 정상/의미 |
|---|---|
| `LD1` green | board 5 V power enabled |
| `LD4` green | ST-LINK power status 정상 |
| `LD4` orange/red/blinking red | short, overcurrent 또는 power error 조사 |
| `LD9` red | ST-LINK initialization |
| `LD9` green/blinking | communication initialized/ongoing |
| `LD9` orange | ST-LINK communication error |

이 보드는 enumeration 과정에서 500 mA 이상을 요구할 수 있다. CN10에 power-only cable을 쓰거나
저전력 hub를 쓰면 ST-LINK 일부만 보이거나 LD1이 켜지지 않을 수 있다.

### External J-Link/Flasher를 사용할 때

1. 보드 자체 전원은 CN10으로 공급한다. CN9는 `[1-2]`로 둔다.
2. 먼저 CN10을 연결하고 onboard ST-LINK가 초기화돼 `LD9`가 red 상태가 될 때까지 기다린다.
3. external J-Link를 MIPI20 `CN1`에 연결한다. 방향/key를 확인한다.
4. J-Link USB를 PC에 연결한다.
5. ARONA programming에는 development boot를 사용한다.

UM3417은 external debugger 사용 시 embedded STLINK-V3EC를 끄지 말고 먼저 실행한 뒤 CN1을
연결하도록 명시한다. J-Link 소프트웨어가 설치돼 있다는 사실만으로 onboard STLINK-V3EC가
J-Link가 되는 것은 아니다.

## 4. Windows/macOS에서 연결 확인

가장 먼저 OS enumeration, debug probe, serial port를 서로 분리해 확인한다. UART port가 보인다는
사실만으로 SWD가 정상이라는 뜻은 아니며, J-Link가 보인다는 사실만으로 onboard ST-LINK가
정상이라는 뜻도 아니다.

### 4.1 공통: repository와 STEdgeAI 확인

```bash
uv sync
uv run arona --help
stedgeai --version
```

예상 STEdgeAI 버전은 `v4.0.1-20581` 계열이다. 다른 Core로 모델을 생성하면 application의
`stedgeai-lib`와 불일치해 `Possible mismatch in ll_aton library used` 오류가 날 수 있다.

Windows PowerShell에서는 repository helper를 사용할 수 있다.

```powershell
. .\scripts\use_stedgeai.ps1
stedgeai --version
```

macOS에서는 설치 위치 중 `stedgeai`가 들어 있는 디렉터리를 PATH에 추가한다.

```bash
export ARONA_STEDGEAI_PATH="/absolute/path/to/stedgeai"
export PATH="$(dirname "$ARONA_STEDGEAI_PATH"):$PATH"
stedgeai --version
```

### 4.2 공통: pyserial로 VCP 목록 확인

ARONA 의존성에 pyserial이 포함돼 있으므로 두 OS에서 같은 명령을 쓸 수 있다.

```bash
uv run python -m serial.tools.list_ports -v
```

onboard VCP의 통신 조건은 `115200`, 8 data bits, no parity, one stop bit, no flow control다.

Windows 예시:

```powershell
uv run python -m serial.tools.miniterm COM5 115200
```

macOS 예시:

```bash
uv run python -m serial.tools.miniterm /dev/cu.usbmodemXXXX 115200
```

`Ctrl+]`로 miniterm을 종료한다. `COM5` 또는 `/dev/cu.usbmodemXXXX`는 고정값으로 추측하지
말고 현재 list_ports 출력에서 선택한다.

### 4.3 Windows에서 USB 장치 확인

```powershell
Get-PnpDevice -PresentOnly |
  Where-Object { $_.FriendlyName -match 'ST-?LINK|STLink|STMicro|J-?Link|USB Serial' } |
  Format-Table Status, Class, FriendlyName, InstanceId -AutoSize

Get-CimInstance Win32_SerialPort |
  Select-Object DeviceID, Name, PNPDeviceID
```

판정:

- ST-LINK composite/debug와 VCP가 모두 보임: host enumeration은 대체로 정상이다.
- `Unknown USB Device`만 보임: cable, port, driver 또는 ST-LINK firmware를 조사한다.
- J-Link만 보임: external J-Link가 보이는 것일 수 있다. external J-Link USB와 CN1을 제거한 후
  CN10만 연결해 다시 검사한다.
- VCP만 보이고 debug interface가 없음: composite driver 또는 ST-LINK firmware 상태를 조사한다.

### 4.4 macOS에서 USB 장치 확인

```bash
system_profiler SPUSBDataType
ls -1 /dev/cu.*
uv run python -m serial.tools.list_ports -v
```

`system_profiler` 출력에서 STMicroelectronics/ST-LINK와 SEGGER/J-Link를 별개 장치로 기록한다.
USB hub나 dock 아래에서만 실패하면 직접 연결과 다른 data cable을 우선 시험한다.

### 4.5 J-Link probe 확인

J-Link Software and Documentation Pack V8.32 이상을 권장한다. Windows executable은 보통
`JLink.exe`, macOS는 `JLinkExe`다.

Windows:

```powershell
JLink.exe -Device STM32N657X0 -If SWD -Speed 1000 -AutoConnect 1
```

macOS:

```bash
JLinkExe -Device STM32N657X0 -If SWD -Speed 1000 -AutoConnect 1
```

처음에는 1 MHz를 사용하고 안정화 후 4 MHz로 높인다. `STM32N657X0` device가 인식되지 않으면
generic Cortex-M55를 대신 선택하지 말고 J-Link pack을 갱신한다. Generic device 선택은 STM32N6
external flash loader를 선택하지 못한다.

### 4.6 VS Code에서 external J-Link debug

VS Code Cortex-Debug extension을 사용하는 최소 `launch.json` 예시는 다음과 같다. ELF 경로는
실제 build 결과로 바꾼다.

```json
{
  "version": "0.2.0",
  "configurations": [
    {
      "name": "NUCLEO-N657X0-Q (J-Link, RAM)",
      "type": "cortex-debug",
      "request": "launch",
      "servertype": "jlink",
      "device": "STM32N657X0",
      "interface": "swd",
      "runToEntryPoint": "main",
      "executable": "${workspaceFolder}/<application-build>/Project.elf"
    }
  ]
}
```

이 설정은 development boot에서 RAM용 ELF를 실행하는 경로다. persistent flash boot image를
생성하거나 signing하는 기능은 아니다.

## 5. `ST-LINK error (DEV_USB_COMM_ERR)` 진단

`DEV_USB_COMM_ERR`는 먼저 PC가 ST-LINK probe와 USB protocol로 통신하지 못했다는 뜻으로
해석한다. target SWD 오류와 구분해서 아래 순서를 바꾸지 않는다.

### 5.1 다른 프로그램의 probe 점유를 제거한다

VS Code debug session, J-Link GDB server, OpenOCD, ST-LINK GDB server, programmer process를 모두
정상 종료한다. 강제 종료 전에 다음 명령으로 남은 process만 기록한다.

Windows:

```powershell
Get-Process -ErrorAction SilentlyContinue |
  Where-Object { $_.ProcessName -match 'JLink|openocd|ST-LINK|STM32_Programmer' } |
  Select-Object ProcessName, Id, Path
```

macOS:

```bash
pgrep -alf 'JLink|openocd|ST-LINK|STM32_Programmer'
```

한 번에 하나의 debug server만 probe를 소유하게 한다.

### 5.2 최소 배선으로 다시 enumerate한다

1. 모든 USB와 CN1 external debugger를 제거한다.
2. shield/camera/display도 제거한다.
3. CN9 `[1-2]`, JP1 `[1-2]`, JP2 `[2-3]`를 확인한다.
4. 알려진 정상 USB-C data cable로 CN10을 PC에 직접 연결한다.
5. LD1, LD4, LD9 상태를 기록한다.
6. OS USB 목록과 serial 목록을 다시 수집한다.

CN8만 연결해 놓고 ST-LINK를 찾지 않는다. CN8은 target user USB다.

### 5.3 USB cable, 전원, hub를 배제한다

- 다른 USB-C data cable
- 다른 PC 직접 포트
- hub/dock/adapter 제거
- 가능하면 다른 Windows/macOS host
- LD1이 꺼져 있으면 CN9 위치와 host가 제공하는 전류부터 재검사
- LD4가 green이 아니면 short/overcurrent 가능성을 먼저 조사

### 5.4 Windows driver를 복구한다

Windows 10/11은 STLINK-V3EC를 기본 인식할 수 있지만, Unknown device로 등록됐거나 Zadig 등으로
다른 libusb driver를 강제로 지정했다면 composite interface가 깨질 수 있다.

1. Device Manager에서 CN10을 뽑고 꽂을 때 사라지고 나타나는 장치를 식별한다.
2. `Unknown USB Device` 또는 교체된 third-party driver인지 확인한다.
3. ST 공식 `STSW-LINK009` driver로 복구한다.
4. 재부팅 또는 USB 재연결 후 composite debug와 VCP를 다시 확인한다.

임의의 J-Link driver를 onboard STLINK-V3EC 장치에 강제 설치하지 않는다.

### 5.5 ST-LINK firmware를 standalone updater로 갱신한다

STM32CubeProgrammer/IDE를 설치하지 않아도 ST 공식 `STSW-LINK007` standalone updater로
STLINK-V3EC firmware를 점검할 수 있다. updater가 probe를 찾으면 최신 compatible firmware로
갱신하고 USB를 다시 연결한다.

업데이트 도중 cable을 분리하지 않는다. updater조차 CN10의 ST-LINK를 찾지 못하고, 두 host와
두 data cable에서도 같은 현상이면 onboard probe firmware corruption 또는 hardware fault 가능성이
높다. 이 경우 external J-Link를 작업 우회로로 사용하고 ST support/RMA를 검토한다.

### 5.6 USB 통신이 회복된 뒤에만 target-level 문제를 조사한다

오류가 `DEV_USB_COMM_ERR`에서 `No target found`, `Cannot halt core` 같은 형태로 바뀌었다면 그때
다음을 시험한다.

- development boot: JP1 `[1-2]`, JP2 `[2-3]`
- B2 target reset
- connect under reset
- SWD 1 MHz 또는 더 낮은 속도
- target voltage가 정상인지 확인

JP2는 이 단계에서 의미가 있다.

### 5.7 “J-Link만 보이고 ST-LINK는 안 보임”의 올바른 해석

NUCLEO-N657X0-Q에는 onboard STLINK-V3EC와 external debug용 CN1이 함께 있다. J-Link가 동작하는
상황은 external J-Link가 CN1을 통해 target에 접근한다는 뜻일 가능성이 가장 높다. 다음 두 경로를
별도로 판단한다.

```text
external J-Link USB -> J-Link/Flasher probe -> CN1 -> target SWD
PC USB -> CN10 -> onboard STLINK-V3EC -> target SWD + VCP + board power
```

external J-Link가 정상이어도 CN10의 onboard ST-LINK USB 문제는 그대로 남을 수 있다. 반대로
onboard ST-LINK debug channel이 고장 나도 VCP가 별도로 enumerate될 수 있으므로 serial 목록을
따로 확인한다.

## 6. CubeIDE/CubeProgrammer 없이 실행하는 세 가지 경로

### 경로 A: 이미 생성·서명된 application을 J-Link로 영구 배포

이 경로는 현재 J-Link/Flasher 연결이 정상일 때 가장 빠르다. 필요한 파일은 다음 세 개다.

```text
FSBL/ai_fsbl.hex
<build>/Application/NUCLEO-N657X0-Q/Project_sign.hex
<generated>/model-files/network_data.hex
```

보드를 development boot로 설정한다. 다음 내용의 J-Link command file을 만든다. placeholder를
실제 absolute path로 치환한다.

```text
r
h
loadfile "<ABSOLUTE_PATH>/ai_fsbl.hex"
loadfile "<ABSOLUTE_PATH>/Project_sign.hex"
loadfile "<ABSOLUTE_PATH>/network_data.hex"
r
q
```

Windows:

```powershell
JLink.exe `
  -Device STM32N657X0 `
  -If SWD `
  -Speed 1000 `
  -AutoConnect 1 `
  -ExitOnError 1 `
  -NoGui 1 `
  -CommandFile .\flash-n657.jlink
```

macOS:

```bash
JLinkExe \
  -Device STM32N657X0 \
  -If SWD \
  -Speed 1000 \
  -AutoConnect 1 \
  -ExitOnError 1 \
  -NoGui 1 \
  -CommandFile ./flash-n657.jlink
```

J-Link는 STM32N657xx의 external flash bank `0x70000000`용 loader를 제공한다. `loadfile` 성공
메시지와 verify 결과를 저장한다. 성공 후 전원을 끄고 JP2를 flash boot `[1-2]`로 바꾼 다음 다시
전원을 연결한다.

> [!WARNING]
> `Project_sign.hex`와 `network_data.hex`가 같은 model generation에서 왔는지 hash/manifest로
> 확인한다. 둘을 잘못 짝지으면 programming은 성공해도 초기화 또는 inference가 실패할 수 있다.

### 경로 B: 새 ONNX를 development boot의 RAM에서 임시 실행

이 경로는 STM32 signing tool 없이 새 build를 시험할 수 있다. 전원을 끄면 RAM application은
사라진다.

1. STEdgeAI로 model code와 `network_data.hex`를 생성한다.
2. external J-Link로 `network_data.hex`를 외부 flash에 program한다.
3. GNU Arm toolchain과 Make로 `Project.elf`를 build한다. `sign` target은 필요 없다.
4. J-Link GDB server와 `arm-none-eabi-gdb`로 ELF를 RAM에 load한다.

J-Link GDB server:

```bash
JLinkGDBServerCLExe -select USB -device STM32N657X0 -if SWD -speed 1000 -port 2331
```

다른 터미널:

```bash
arm-none-eabi-gdb "/absolute/path/to/Project.elf"
```

GDB:

```text
target remote :2331
monitor reset
load
continue
```

ST 공식 example도 development mode에서 GDB `load` 후 `continue`하는 방식을 사용한다.

### 경로 C: 새 ONNX를 영구 flash boot image로 생성

STEdgeAI 4.0.1만으로는 충분하지 않다. 다음이 모두 필요하다.

- STEdgeAI 4.0.1
- GNU Arm Embedded Toolchain: `arm-none-eabi-gcc`, `objcopy`, `gdb`
- GNU Make
- model과 같은 Core의 `stedgeai-lib`
- STM32N6 header v2.3을 만드는 `STM32_SigningTool_CLI` 또는 이미 서명된 application
- J-Link/Flasher 또는 다른 STM32N6 external-flash capable programmer

strict하게 STM32CubeProgrammer package와 signing tool을 모두 금지하면, 현재 repository와 ST
공식 example만으로 **새 persistent application을 서명할 수 없다**. 이 경우 경로 B로 RAM에서
시험하거나, 별도 build machine에서 만든 `Project_sign.hex`를 받아 경로 A로 program한다.

STM32CubeProgrammer GUI를 사용하지 않는 것과 `STM32_Programmer_CLI`까지 사용하지 않는 것은
다른 조건이다. 현재 `arona deployment program`은 후자의 CLI와 ST external loader에 의존한다.
따라서 strict no-CubeProgrammer 환경에서는 해당 ARONA 명령을 실행하지 말고 J-Link 경로를 쓴다.

## 7. STEdgeAI 4.0.1로 새 ONNX 배포 파일 생성

### 7.1 Windows ARONA generate 경로

classification 예시:

```powershell
. .\scripts\use_stedgeai.ps1
stedgeai --version

uv run arona deployment generate `
  --application image_classification `
  --model-support-directory outputs/vendor/STM32N6-GettingStarted-ImageClassification/Model `
  models/downloads/mobilenetv2_a035_128_food101_qdq.onnx `
  -o outputs/deployment/image-classification/generated
```

object detection 예시:

```powershell
uv run arona deployment generate `
  --application object_detection `
  --model-support-directory outputs/vendor/STM32N6-GettingStarted-ObjectDetection/Model `
  models/downloads/yolo26n_256_coco_person_qdq_int8.onnx `
  -o outputs/deployment/object-detection/generated
```

성공 조건:

```text
<output>/model-files/network.c
<output>/model-files/network_ecblobs.h
<output>/model-files/stai_network.c
<output>/model-files/stai_network.h
<output>/model-files/network_atonbuf.xSPI2.raw
<output>/model-files/network_data.hex
```

ARONA의 현재 automatic tool discovery는 Windows executable 이름을 우선하므로, macOS에서는
다음 직접 생성 경로를 쓰는 것이 확실하다.

### 7.2 macOS 또는 수동 CLI generate 경로

`OUTPUT_TYPE`은 현재 image classification이면 `float32`, object detection이면 `int8`을 사용한다.

```bash
MODEL="/absolute/path/to/model.onnx"
SUPPORT="/absolute/path/to/outputs/vendor/STM32N6-GettingStarted-ImageClassification/Model"
OUT="/absolute/path/to/outputs/deployment/generated"
OUTPUT_TYPE="float32"

mkdir -p "$OUT/stedgeai-output" "$OUT/workspace" "$OUT/model-files"

stedgeai generate \
  --model "$MODEL" \
  --target stm32n6 \
  --type onnx \
  --st-neural-art "default@$SUPPORT/user_neuralart_NUCLEO-N657X0-Q.json" \
  --input-data-type uint8 \
  --output-data-type "$OUTPUT_TYPE" \
  --inputs-ch-position chlast \
  --workspace "$OUT/workspace" \
  --output "$OUT/stedgeai-output" \
  --with-report

cp "$OUT/stedgeai-output/network.c" "$OUT/model-files/"
cp "$OUT/stedgeai-output/network_ecblobs.h" "$OUT/model-files/"
cp "$OUT/stedgeai-output/stai_network.c" "$OUT/model-files/"
cp "$OUT/stedgeai-output/stai_network.h" "$OUT/model-files/"
cp "$OUT/stedgeai-output/network_atonbuf.xSPI2.raw" "$OUT/model-files/"

arm-none-eabi-objcopy \
  -I binary "$OUT/model-files/network_atonbuf.xSPI2.raw" \
  --change-addresses 0x70380000 \
  -O ihex "$OUT/model-files/network_data.hex"
```

### 7.3 STEdgeAI runtime 동기화

생성에 사용한 Core 4.0.1과 application runtime을 맞춘다.

```bash
uv run arona deployment sync-runtime \
  --core-directory "/absolute/path/to/STEdgeAI/4.0" \
  "/absolute/path/to/outputs/vendor/STM32N6-GettingStarted-ImageClassification/Application/NUCLEO-N657X0-Q" \
  -o outputs/deployment/runtime-sync
```

### 7.4 application build

필요한 source instrumentation과 MVP 설정:

```bash
uv run arona deployment instrument \
  --application image_classification \
  outputs/vendor/STM32N6-GettingStarted-ImageClassification/Application/NUCLEO-N657X0-Q

uv run arona deployment configure \
  --application image_classification \
  outputs/vendor/STM32N6-GettingStarted-ImageClassification/Application/NUCLEO-N657X0-Q
```

카메라가 없으면 build 전에 fixed-input mode를 적용한다.

```bash
uv run arona deployment fixed-input \
  --application image_classification \
  outputs/vendor/STM32N6-GettingStarted-ImageClassification/Application/NUCLEO-N657X0-Q
```

수동 Make build 예시:

```bash
cd outputs/vendor/STM32N6-GettingStarted-ImageClassification/Application/NUCLEO-N657X0-Q

make -j8 \
  BUILD_TOP=build-agent \
  GCC_PATH="/absolute/path/to/arm-none-eabi/bin" \
  MODEL_DIR="/absolute/path/to/generated/model-files" \
  SCR_LIB_SCREEN_ITF=UVCL
```

이 명령은 unsigned `Project.elf`와 `Project.bin`을 만든다. persistent flash boot용 `Project_sign.hex`는
signing tool이 있는 build environment에서 생성해야 한다.

새로운 임의 ONNX는 input shape/type뿐 아니라 application preprocessing, class label, output tensor,
postprocessing과 맞아야 한다. 현재 `configure`는 선택된 MVP 모델을 지원한다. 완전히 다른 모델을
아무 수정 없이 올릴 수 있다고 가정하지 않는다.

## 8. 실행 결과 확인

### Flash boot validation

1. programming tool이 모든 load/verify를 성공했다고 출력했는지 확인한다.
2. 전원을 제거한다.
3. JP1 `[1-2]`, JP2 `[1-2]`로 flash boot를 설정한다.
4. CN10을 다시 연결한다.
5. 현재 VCP를 다시 탐지한다.
6. UART에서 최소 5개의 명시적 inference record를 확인한다.

```bash
uv run arona deployment validate \
  --application image_classification \
  --serial-port COM5 \
  --inference-count 5 \
  --capture-seconds 30 \
  -o outputs/deployment/validate
```

정상 telemetry 예시:

```text
ARONA_INFERENCE seq=1 latency_ms=3 class=pizza score=0.91
```

programming 성공, boot banner, UVC enumeration만으로 모델 inference 성공이라고 판정하지 않는다.

### UART가 보이지 않을 때

- CN10 ST-LINK composite 장치와 VCP가 OS에 있는지 먼저 확인한다.
- 다른 serial terminal이 port를 점유하고 있지 않은지 확인한다.
- baud를 `115200`, 8-N-1, no flow로 고정한다.
- external J-Link를 쓰더라도 UART는 기본적으로 CN10의 onboard ST-LINK VCP를 사용한다.
- onboard VCP 자체가 복구되지 않으면 current ARONA telemetry를 읽기 위해 별도 USB-UART와
  board schematic 기반 배선/격리가 필요하다. 이 작업은 SWD/J-Link 연결과 별개의 문제다.

## 9. 에이전트용 진단 결정표

| 관찰 | 가장 먼저 예상할 원인 | 다음 행동 |
|---|---|---|
| CN10 연결 후 아무 USB 장치도 없음 | wrong connector, power-only cable, hub, CN9, hardware | CN10/CN9/케이블/직결/LED 확인 |
| J-Link만 보임 | external J-Link만 enumerate | external J-Link 제거 후 CN10 단독 검사 |
| ST-LINK가 Unknown device | Windows composite driver 또는 firmware | STSW-LINK009, STSW-LINK007 |
| ST-LINK와 VCP가 보이지만 `DEV_USB_COMM_ERR` | process lock, stale USB state, firmware, unstable USB | debug server 종료, replug, direct port, firmware update |
| ST-LINK USB 정상, target not found | boot/reset/SWD speed/target power | development boot, B2, under reset, 1 MHz |
| J-Link가 generic Cortex-M55로만 연결 | J-Link pack이 오래됨 | V8.32+ 갱신, `STM32N657X0` 선택 |
| J-Link RAM load 성공, power cycle 후 사라짐 | 정상 development-mode 특성 | persistent image는 sign 후 external flash 배포 |
| J-Link programming 성공, flash boot 안 됨 | JP2, artifact pairing, signing/FSBL/address | JP2 `[1-2]`, 세 artifact와 hash 재검사 |
| `ll_aton` version mismatch | Core와 runtime 불일치 | Core 4.0.1 runtime sync 후 clean build |
| model initialization 실패 | app/model code/network data 불일치 | 같은 generation artifact로 다시 build/program |
| UART만 없음 | VCP/port/baud/점유 문제 | SWD와 분리해 VCP 진단 |

## 10. 다른 에이전트에게 넘길 관찰 템플릿

문제 해결을 요청할 때 다음 블록을 채워 그대로 전달한다. 에이전트는 값이 비어 있으면 추측하지
말고 해당 read-only 확인부터 안내해야 한다.

```text
OS/version:
Host architecture: Intel/Apple Silicon/x64/arm64
Board marking/revision:

Power/data wiring:
- CN10 cable connected: yes/no
- CN8 cable connected: yes/no
- External J-Link USB connected: yes/no
- J-Link to CN1 connected: yes/no
- CN9 position:

Boot:
- JP1 physical pins:
- JP2 physical pins:
- Desired operation: probe / RAM debug / external-flash program / flash boot

LEDs after CN10 connection:
- LD1:
- LD4:
- LD9:

OS USB enumeration, exact output:
<paste Get-PnpDevice or system_profiler excerpt>

Serial enumeration, exact output:
<paste python -m serial.tools.list_ports -v>

Running debug/program processes:
<paste process-list command>

Tools:
- stedgeai --version:
- JLink/JLinkExe version:
- arm-none-eabi-gcc --version:
- make --version:

Probe command and full first error:
<paste command, stdout, stderr, exit code>

Artifacts intended for programming:
- FSBL path + SHA-256:
- Project_sign path + SHA-256:
- network_data path + SHA-256:
- generation/build manifest path:
```

## 11. 이 repository에서의 현재 제한

- `arona deployment generate`: Windows automatic tool discovery 기준으로 구현돼 있다. macOS에서는
  STEdgeAI와 objcopy를 직접 실행하는 경로가 더 확실하다.
- `arona deployment build`: Windows에서 CubeIDE bundle 또는 PATH의 Make/GCC/signing tool을
  찾도록 구현돼 있다. macOS에서는 Makefile을 직접 실행한다.
- `arona deployment program`: 현재 `STM32_Programmer_CLI`와 ST `.stldr` external loader를
  사용한다. J-Link backend는 아직 ARONA CLI에 통합돼 있지 않다.
- `arona deployment validate`: pyserial 기반이라 올바른 VCP가 있으면 Windows/macOS에서 사용할
  수 있다.
- STEdgeAI 4.0.1은 model code generation 도구이지 programmer, linker 또는 signing tool이 아니다.

따라서 다른 에이전트는 strict no-CubeProgrammer 환경에서 `arona deployment program`을 반복
실행시키지 말고, 먼저 external J-Link 여부와 signed artifact 보유 여부를 확인해야 한다.

## 12. 근거 문서

Repository-local ST 문서:

- [Image classification Getting Started README](../outputs/vendor/STM32N6-GettingStarted-ImageClassification/README.md)
- [Object detection Getting Started README](../outputs/vendor/STM32N6-GettingStarted-ObjectDetection/README.md)
- [ST model generation 설명](../outputs/vendor/STM32N6-GettingStarted-ImageClassification/Doc/Deploy-your-Quantized-Model.md)
- [ARONA deployment 절차](deployment.md)
- [NUCLEO deployment template](../deployment/templates/nucleo-n657x0-q.yaml)

공식 보드/도구 문서:

- [ST UM3417: STM32N6 Nucleo-144 board MB1940 user manual](https://www.st.com/resource/en/user_manual/dm01122391-.pdf)
- [ST ST-LINK firmware updater STSW-LINK007](https://www.st.com/en/development-tools/stsw-link007.html)
- [SEGGER NUCLEO-N657X0-Q board note](https://kb.segger.com/ST_NUCLEO-N657X0-Q)
- [SEGGER STM32N6 flash support](https://kb.segger.com/ST_STM32N6)
- [SEGGER J-Link Commander](https://kb.segger.com/J-Link_Commander)

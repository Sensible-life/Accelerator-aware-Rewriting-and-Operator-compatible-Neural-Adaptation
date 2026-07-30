# ST Edge AI backend decision

## Sprint 0 결정

- Primary board: `NUCLEO-N657X0-Q`
- Accelerator: ST Neural-ART
- Backend ID: `stedgeai`
- Vendor compiler entry point: `stedgeai`
- Host mode: NUCLEO board가 USB/ST-LINK로 연결된 개발 PC

STM32N6 backend를 MVP의 첫 end-to-end backend로 구현한다. `NUCLEO-H753ZI`는 필요할
때 CPU-only 비교 대상으로 사용하고, Renesas EK-RA8P1 backend는 primary pipeline이
안정화된 뒤 추가한다.

## 아직 고정해야 하는 로컬 환경 값

다음 값은 연구실 개발 PC에서 실제 설치와 baseline compile을 수행한 뒤 기록한다. 문서의
빈 값을 추정 버전으로 채우지 않는다.

| 항목 | 고정 값 |
| --- | --- |
| ST Edge AI Core / `stedgeai` | TBD |
| STM32Cube AI Studio 또는 X-CUBE-AI | TBD |
| STM32CubeProgrammer | TBD |
| STM32CubeCLT / compiler | TBD |
| ST-LINK firmware | TBD |
| NUCLEO board revision | TBD |
| validation firmware commit/hash | TBD |

## 예정된 증거 보관 위치

```text
tests/fixtures/backends/stedgeai/<case-id>/
├── model.onnx
├── input.npz
├── command.txt
├── environment.json
├── compiler/
└── expected-analysis.json
```

대용량 compiler binary와 vendor redistributable 파일은 저장소에 commit하지 않는다.
라이선스상 배포 가능한 log, JSON report, 명령, checksum만 fixture로 보관한다. 실제 run
산출물은 `outputs/<run-id>/compiler/`에 저장한다.

첫 재현 사례는 software fallback이 포함된 quantized ONNX와 exact rewrite 적용 모델의
두 baseline을 사용한다. 후보 규칙은 `SiLU(x) -> x * Sigmoid(x)`이며, 실제 설치된 compiler
버전에서 HW/SW mapping 차이가 관찰될 때 최종 fixture로 채택한다.

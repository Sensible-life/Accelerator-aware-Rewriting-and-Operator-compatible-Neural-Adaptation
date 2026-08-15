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
├── command.txt
├── environment.json
└── compiler.log
```

대용량 compiler binary와 vendor redistributable 파일은 저장소에 commit하지 않는다.
라이선스상 배포 가능한 log, JSON report, 명령, checksum만 fixture로 보관한다. 실제 run
산출물은 `outputs/<run-id>/compiler/`에 저장한다.

현재 Sprint 1/2 fixture는 다음 두 사례를 보존한다.

| case-id | 목적 | 핵심 판정 |
| --- | --- | --- |
| `conmamba_fallback` | 1,530 / 2,072 software epoch와 잘못된 HyperRAM activation pool 진단 | compiler scheduling 단계에서 실제 board memory profile과 맞지 않아 deployability 실패 |
| `conmamba_xip_101` | code/constant를 XIP flash로 옮긴 101-sequence 사례 | activation pool이 실제 SRAM region 안에 있어 deployability feasible |

이 fixture는 원본 ConMamba model/binary를 저장하지 않는다. 재배포 가능한 compiler log,
실행 command, 환경 metadata만 저장하고, 라이선스상 저장할 수 없는 산출물은 checksum과
생성 절차로 대체한다.

`src/arona/backends/stedgeai/parsers.py`는 현재 ARONA fixture 형식과 일반적인 사람이 읽는
log 문구를 정규화한다. 실제 연구실 PC에서 확보한 원문 `stedgeai` log 형식은 같은 contract를
유지한 채 parser rule만 추가한다.

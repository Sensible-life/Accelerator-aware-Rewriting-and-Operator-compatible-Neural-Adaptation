# Checkpoint 4 end-to-end evidence

검증일은 2026-08-22이며, 대상은 `NUCLEO-N657X0-Q` revision B와 ST Neural-ART다.
이 문서는 `e57bde8038178603337605afbd9426ef51200fa0`의 checkpoint 4 상태를 다시
검증하면서 새로 생성한 실기기 증거를 요약한다. 모델, vendor checkout, build output과 flash
dump는 라이선스와 용량 때문에 Git에 넣지 않으며, 재생성 명령과 checksum은
`tests/fixtures/deployment/nucleo_checkpoint4_e2e/evidence.json`에 고정한다.

## 검증 환경

- ST Edge AI Core `v4.0.1-20581 7ed50de05`
- STM32CubeProgrammer `v2.22.0`
- ST-LINK firmware `V3J15M6`, serial `004000173234510E37333934`
- STM32N657 device ID `0x486`, revision B, Cortex-M55
- COM5, 115200 baud

Programming 전에 external flash 64 MiB를 백업했다. 백업 파일 크기는 67,108,864 bytes이고
SHA-256은 `acc2fbeb5308230ce6350878138f830440094f53d6d677e16a63771486293dd3`이다.
첫 백업은 기존 180초 timeout 때문에 86%에서 중단됐으며, 이 검증 중 기본 timeout을 600초로
수정한 뒤 재실행해 성공했다.

## 결과

| Model | Core placement | Board inference | Fixed input |
| --- | --- | --- | --- |
| MobileNetV2 0.35 Food-101 128 QDQ | 55 epochs: NPU 54, software 1 | 343/343, 2–3 ms, mean 2.647 ms | `0xfbe51dc5` |
| YOLO26n COCO-Person 256 QDQ Int8 | 176 epochs: NPU 162, software 14 | 150/150, 20–21 ms, mean 20.953 ms | `0x6c3e9dc5` |

두 모델 모두 fresh `analyze/optimize -> generate -> build/sign -> exact-board probe -> program/verify
-> UART inference validation`을 통과했다. 현재 유일한 rewrite인 terminal ArgMax externalization은
두 원본 모델의 출력 구조에 해당하지 않아 안전하게 거부됐고, ARONA는 baseline을 배포 모델로
유지했다. 따라서 이 결과는 하드웨어 최적화·배포 기능 MVP를 입증하지만, 선택 모델에서 CPU
fallback을 감소시켰다는 증거는 아니다.

실행 중 physical JP2 전환이 필요하므로 실제 검증은 ARONA의 resumable deployment 명령을
사용했고, 마지막에 `--deployment-result`로 compiler 분석과 UART 결과를 하나의 run report에
결합했다. `arona optimize --deploy`에도 programming 후 Flash boot 전환 확인 프롬프트를
추가했고 해당 sequence는 회귀 테스트로 고정했다.

로컬 최종 보고서:

- `outputs/checkpoint4-e2e/final-runs/mobilenet/20260822T135115Z-optimize/report.md`
- `outputs/checkpoint4-e2e/final-runs/yolo/20260822T135115Z-optimize/report.md`

## 재현성 상태

- tracked source만 추출한 clean archive에서 새 Python 3.11 환경과 `uv sync --frozen` 설치 성공
- clean archive pytest: 48 passed, 1 hardware test skipped
- 현재 작업 트리 전체 품질 gate: pytest, Ruff format/lint, mypy 통과
- 모델 다운로드와 vendor application 확보부터 physical JP2 전환까지 완전히 새 PC 한 대에서
  한 번에 재현하는 시험은 아직 남아 있다.


# ARONA 4일 MVP 구현 계획

> 기간: 2026-08-21 ~ 2026-08-24
> 제출 전 버퍼: 2026-08-25 ~ 2026-08-26
> 제출: 2026-08-27 18:00

## 1. MVP 목표

MVP의 목표는 범용 최적화기를 완성하는 것이 아니다. 다음 한 문장을 실제 보드 증거로
입증하는 데 집중한다.

> ARONA가 ONNX 모델을 분석하고, NUCLEO-N657X0-Q/Neural-ART에 불리한 실행 구간을
> 한정된 안전 규칙으로 수정한 뒤, 수정 모델을 다시 컴파일·검증·보드에 배포할 수 있다.

필수 데모 경로는 다음과 같다.

```text
ONNX QDQ 모델
  -> 실제 stedgeai baseline 분석
  -> fallback/메모리/배포 가능성 진단
  -> 안전한 규칙 1개 적용
  -> ONNX Runtime 동등성 검증
  -> optimized model 재컴파일
  -> NUCLEO-N657X0-Q programming/inference
  -> 전후 비교 report.md
```

### MVP 완료 조건

- [x] 깨끗한 PC 환경에서 `arona optimize <model> --target stedgeai --deploy` 한 경로로 재현한다.
  - 2026-08-24 외부 Windows PC에서 `arona deployment generate -> sync-runtime -> instrument/configure/fixed-input -> build -> program -> validate` 단계별 E2E를 재현했다.
  - MobileNetV2 fixed-input 2,049회, YOLO26n fixed-input 927회 validation 성공.
  - `uv run arona optimize ... --deploy` 단일 명령 재현 성공: `outputs/demo-runs/20260824T001942Z-optimize`.
- [ ] baseline과 optimized 모델 모두 실제 `stedgeai`로 컴파일하고 원문 log를 보존한다.
- [ ] 최소 한 모델에서 CPU software epoch, fallback operator 또는 NPU/CPU transition이 감소한다.
- [x] 최적화가 개선되지 않으면 baseline을 유지하고 그 이유를 보고한다.
- [x] 고정 입력 최소 10개로 원본과 최적화 모델의 end-to-end 결과 동등성을 검증한다.
- [x] ARONA가 선택한 deployable model을 NUCLEO-N657X0-Q에 programming하고 연속 inference
  최소 5회를 확인한다. 두 선정 모델 모두 rewrite 비대상이라 baseline을 유지했다.
  - external Windows E2E: MobileNetV2 fixed-input 2,049회, YOLO26n fixed-input 927회 검증 성공.
  - external Windows `optimize --deploy`: MobileNet terminal ArgMax variant 2,280회 검증 성공, 평균 2.644 ms.
- [x] 모델 checksum, toolchain/firmware/board revision, 명령, exit code, latency와 memory를 기록한다.
  - evidence: `docs/checkpoint4-e2e-evidence.md`
- [x] `pytest`, Ruff format/lint, mypy가 모두 통과한다.

## 2. 목표 보드와 탑재 모델 확정

- 목표 보드: `NUCLEO-N657X0-Q` (`STM32N657`, Neural-ART NPU)
- 연결: ST-LINK USB/SWD + Virtual COM Port `COM5`
- MVP 모델은 아래 두 개로 고정하며, 224x224 MobileNetV2를 포함한 대체 모델은 구현 범위에서 제외한다.

### P0-1 — MobileNetV2 0.35, Food-101, 128x128, ONNX QDQ

- 로컬 이름: `mobilenetv2_a035_128_food101_qdq.onnx`
- 원본: ST 공식 STM32 Model Zoo의 `mobilenetv2_a035_128_fft` QDQ mixed Int8/Int4 모델
- 역할: 가장 먼저 보드 배포를 성공시킬 golden model이자 최적화 전·후 비교 모델
- 선택 이유:
  - 현재 ARONA의 ONNX frontend를 그대로 사용할 수 있다.
  - ST가 STM32N6/Neural-ART용으로 측정한 공식 모델이다.
  - 공식 기준 internal RAM 240 KiB, external RAM 0 KiB, weights Flash 약 396.44 KiB다.
  - STM32N6570-DK 참고 inference time은 약 2.65 ms다.
  - 메모리 여유가 커서 보드·toolchain 문제와 모델 문제를 분리하기 쉽다.

#### 최적화 데모 입력

공식 모델 자체는 이미 배포 친화적이므로, 실제 사용자 export에서 흔히 생기는 terminal
`ArgMax` 포함 variant를 fixture 생성 스크립트로 만든다. 이 파생 모델임을 보고서에 명시한다.

- baseline: confidence tensor 뒤의 `ArgMax`가 Cortex-M55 `SW_INT` fallback
- optimized: terminal `ArgMax`를 모델 밖의 MCU post-processing으로 이동
- 검증: optimized logits에 같은 ArgMax를 적용한 end-to-end class index가 baseline과 동일
- 기대 효과: 모델 내부 software epoch/partition 제거 또는 감소

추가로 graph와 compiler version이 허용할 때만 다음 compiler option을 자동 선택한다.

- terminal `Softmax`가 있으면 `--expand-softmax` 전후를 실제 compiler 결과로 비교한다.
- expanded Swish 패턴이 있으면 `--SWISH-recognition` 적용 여부를 비교한다.
- 측정 차이가 없는 option은 최적화 성과로 보고하지 않는다.

### P0-2 — YOLO26n, COCO-Person, 256x256, ONNX QDQ Int8

- 로컬 이름: `yolo26n_256_coco_person_qdq_int8.onnx`
- 역할: 카메라 기반 object detection 시연으로 범용성과 시각적 효과를 보강
- ST 공식 Model Zoo에서 STM32N6 지원·권장으로 표시한 ONNX QDQ 모델
- 공식 기준 internal RAM 약 722.04 KiB, external RAM 0 KiB, weights Flash 약 2,341.32 KiB
- STM32N6570-DK 참고 inference time 약 20.99 ms
- 필수 두 번째 탑재 모델이며 MobileNet golden path가 열린 직후 analyze/compile/deploy한다.
- 외부 Ultralytics/ST fork의 AGPL-3.0 라이선스 조건을 확인하고 출처·checksum을 기록한다.
- YOLO graph rewrite, NMS 삽입, 재학습 또는 정확도 튜닝은 하지 않는다. 분석·컴파일·배포
  회귀와 보드 smoke test까지 수행한다.

### 이번 MVP에서 제외할 모델

- `ConMamba`: 원본 모델이 저장소에 없고 fallback·메모리 문제가 커서 4일 내 실기기 성공 위험이 높다.
- FdMobileNet 및 `st_yoloxn` 기본 배포 예시: 빠르고 공식 예제가 있지만 주 배포 파일이
  TFLite라 현재 ONNX-only frontend 범위를 넓혀야 한다.
- EfficientNetV2, ResNet50V2: 메모리와 컴파일 시간이 크고 일부 모델은 external RAM이 필요하다.
- neural adaptation/fine-tuning이 필요한 모델: 데이터·학습·정확도 회귀 검증 시간이 부족하다.

## 3. 구현 범위 고정

### 반드시 구현한다

- [x] 실제 `stedgeai` toolchain 탐지와 현재 버전 증거 고정
- [ ] Core 4.0.0 live compile 성공 결과 수집 및 실제 metric report parser
- [x] terminal ArgMax externalization 규칙 1개
- [x] 원본/최적화 ONNX Runtime end-to-end 검증
- [x] compiler-in-the-loop 전후 비교와 개선된 경우에만 채택
- [ ] ST 공식 N6 deployment workflow를 호출하는 최소 deploy/program wrapper
- [ ] 보드 실행 증거와 Markdown/JSON 통합 보고서

### 구현하지 않는다

- 범용 rewrite rule engine과 두 번째 backend
- TFLite frontend
- quantizer 자체 구현
- neural adaptation, fine-tuning, distillation
- 웹 UI
- 임의 ONNX 모델에 대한 지원 보장
- YOLO graph rewrite, NMS 삽입 또는 재학습 기반 최적화
- 실제로 측정하지 않은 latency, memory 또는 accuracy 수치 생성

## 4. Day 1 — 실기기 golden path와 데이터 고정

목표: 코드 구현 전에 공식 모델 하나가 현재 PC에서 실제 보드까지 올라가는지 확인한다.

### 오전: 환경과 모델 고정

- [x] ST Edge AI Core, X-CUBE-AI, STM32CubeProgrammer, STM32CubeIDE/CLT, ST-LINK firmware 버전을 기록한다.
- [x] `stedgeai supported-ops -t onnx --with-report` 결과를 fixture로 보존한다.
- [x] NUCLEO-N657X0-Q를 COM5/ST-LINK/SWD로 식별하고 MCU·revision·전압을 기록한다.
- [x] boot mode와 카메라 연결 상태를 기록한다(카메라 미연결, fixed-input smoke로 대체).
- [x] 선정한 MobileNetV2 128 및 YOLO26n 256 ONNX QDQ 모델을 공식 저장소에서 확보한다.
- [x] 각 모델의 원본 URL, 라이선스, SHA-256, input/output name·shape·dtype를 manifest에 기록한다.
- [x] 모델 binary는 라이선스와 용량을 확인한 뒤 commit 여부를 결정하고, 미포함 시 다운로드 스크립트와 checksum만 저장한다.

### 오후: ARONA 밖에서 먼저 golden deployment

- [ ] ST 공식 `stm32ai-modelzoo-services` image classification N6 workflow로 P0 128 모델을 배포한다.
- [ ] programming 성공과 inference 최소 5회를 확인한다.
- [x] 같은 모델을 실제 `stedgeai analyze`로 실행하고 원문 log/report를 보존한다.
- [x] 실제 report에서 node/epoch/fallback/memory/stage를 추출할 수 있는 최소 parser를 구현한다.
- [x] 기존 합성 fixture와 실제 toolchain fixture를 명확히 분리한다.

### Day 1 종료 gate

- [ ] **필수:** 공식 MobileNetV2 모델이 ARONA 밖의 공식 workflow로 보드에서 실행된다.
- [x] **필수:** baseline compiler log와 toolchain/board metadata를 확보했다.
- [ ] 실패 시 Day 2 rewrite 개발을 시작하지 않고 설치·boot mode·firmware·전원 문제 해결에 집중한다.
- [ ] Day 1 종료까지 보드 경로가 열리지 않으면 최종 시연 범위를 `compile + generated artifact`로
  축소하고 “실기기 미검증”을 명시한다.

### Commit checkpoint 1

- [x] 환경·보드 evidence, 모델 manifest/download script, toolchain 자동 탐지 테스트가 함께 통과하면 커밋한다.
- 권장 메시지: `chore: pin MVP models and capture NUCLEO day1 evidence`

## 5. Day 2 — 최소 최적화와 검증 loop

목표: 한 규칙을 안전하게 적용하고 compiler 결과가 개선될 때만 채택한다.

### graph rewrite

- [x] `src/arona/graph/`에 최소 `RewriteRule` 인터페이스와 terminal ArgMax 규칙을 추가한다.
- [x] ArgMax가 graph output의 유일한 producer이고 결과가 다른 node에서 사용되지 않을 때만 후보로 잡는다.
- [x] optimized graph output을 ArgMax 입력 confidence/logit tensor로 교체한다.
- [x] MCU에서 수행할 axis/keepdims/output dtype 정보를 `postprocess.json`으로 저장한다.
- [x] 원본 model은 수정하지 않고 `optimized-model.onnx`를 새로 저장한다.
- [x] 적용·거절 이유와 affected node ID를 `RewriteRecord`에 기록한다.

### validation

- [x] 고정 seed random input을 최소 10개 생성한다.
- [ ] 라이선스상 저장 가능한 실제 이미지 validation input을 확보한다.
- [x] baseline ONNX output과 `ArgMax(optimized ONNX output)`을 비교한다.
- [x] class index가 모두 같아야 통과하며 mismatch 시 후보를 자동 거절한다.
- [x] validation exception과 NaN/Inf를 실패로 처리한다.

### compiler-in-the-loop

- [x] pipeline이 baseline live compile → candidate compile 순서로 adapter를 호출하게 한다.
- [x] software epoch, fallback operator, transition, activation, deployability를 비교한다.
- [x] 동등성 통과와 compiler 개선을 모두 만족할 때만 `decision.selected=optimized`로 설정한다.
- [x] 개선이 없거나 compile이 실패하면 baseline을 유지한다.
- [ ] `--expand-softmax`, `--SWISH-recognition`은 graph에서 근거가 있을 때만 후보 option으로 시험한다.

### 테스트

- [x] terminal ArgMax 적용/거절/다중 consumer/axis/keepdims 테스트
- [x] validation pass/fail 테스트
- [x] candidate compile 실패 시 baseline 원복 테스트
- [x] 실제 log fixture parser regression 테스트

### Day 2 종료 gate

- [ ] MobileNetV2 128 파생 모델에서 baseline과 optimized compiler report의 차이를 자동 생성한다.
- [x] optimized model과 postprocess를 합친 end-to-end 결과가 10/10 일치한다.
- [x] 개선이 없으면 수치를 꾸미지 않고 rule/모델 조합을 폐기한다.

### Commit checkpoint 2

- [x] rewrite, 동등성 검증, compiler-in-the-loop 테스트가 모두 통과하면 커밋한다.
- 권장 메시지: `feat: add compiler-validated terminal argmax rewrite`

## 6. Day 3 — 배포 통합과 보드 검증

목표: ARONA가 선택한 optimized model을 실제 NUCLEO에 올리고 실행 증거를 남긴다.

### deployment wrapper

- [x] ST 공식 image classification N6 config를 기반으로 repository-local template를 만든다.
- [x] model path, board, boot mode, tool 경로만 ARONA가 채우도록 한다.
- [x] build/program command, exit code, stdout/stderr, 생성 artifact를 run directory에 저장한다.
- [x] programming, initialization, inference, validation stage를 실제 결과로 갱신한다.
- [x] timeout과 최초 오류를 보존하고 실패를 `completed`로 표시하지 않는다.

### board validation

- [x] MobileNetV2 128 선정 모델을 programming한다(적용 가능한 개선 rewrite가 없으면 baseline 유지).
- [x] serial/debug output 또는 공식 application 출력으로 연속 inference 5회를 확인한다.
  - MobileNet fixed-input: 1,021회, 2–3 ms(평균 2.643 ms), model/hash 검증 성공
  - external Windows rerun: 2,049회, 2–3 ms(평균 2.643 ms), model/hash 검증 성공
  - external Windows `optimize --deploy`: 2,280회, 2–3 ms(평균 2.644 ms), run `outputs/demo-runs/20260824T001942Z-optimize`
  - evidence: `outputs/checkpoint3/image-classification/fixed-input-aligned-validate/`
- [ ] 가능하면 baseline/optimized target latency를 같은 조건에서 각각 20회 측정한다.
- [x] 측정이 불가능하면 compiler estimate와 target measurement를 혼합하지 않는다.
- [x] YOLO26n 원본을 analyze/compile한다.
- [x] YOLO26n을 NUCLEO-N657X0-Q에 programming한다.
- [x] 고정 입력 또는 카메라 입력으로 person detection inference 5회를 확인한다.
  - YOLO fixed-input: 618회, 20–21 ms(평균 20.937 ms), model/hash 검증 성공
  - external Windows rerun: 927회, 20–21 ms(평균 20.939 ms), model/hash 검증 성공
- [x] 카메라가 준비되지 않으면 고정 input binary와 serial/debug 결과로 보드 실행을 증명한다.

### Day 3 종료 gate

- [x] ARONA가 선택한 deployable model(rewrite 이득이 없어 baseline 유지)이 NUCLEO-N657X0-Q에서 실행된다.
- [x] 한 run directory에 원본/최적화 분석, rewrite, validation, compiler, deployment 증거가 모두 있다.
  - evidence index: `outputs/checkpoint3/CHECKPOINT3_EVIDENCE.md`

### Commit checkpoint 3

- [x] 두 선정 모델의 보드 실행 증거와 deploy wrapper 회귀 테스트를 확보한 뒤 커밋한다.
- 권장 메시지: `feat: deploy MVP models to NUCLEO-N657X0-Q`

## 7. Day 4 — CLI, 보고서, 회귀 테스트와 시연 고정

목표: 개발자 PC가 아닌 깨끗한 환경에서도 같은 데모를 한 번에 재현한다.

### CLI와 산출물

- [x] checkpoint 4 UX를 고정한다. `arona optimize --deploy`가 STM32N6
  generate/build/program/validate sequence를 실행하고, `--deployment-result <json>`은 기존 검증
  결과를 run report에 결합하는 우회 경로로 사용한다.

  ```bash
  arona optimize models/mobilenetv2-demo.onnx \
    --target stedgeai \
    --validation-input inputs/demo \
    --deploy
  ```

- [x] deployment가 실행된 run directory에 다음을 생성한다.

  ```text
  original-analysis.json
  optimized-model.onnx
  optimized-analysis.json
  rewrite-history.json
  postprocess.json
  validation.json
  compiler/
  deployment/
  report.md
  ```

- [x] `report.md`에 before/after software epoch, fallback, memory, latency, validation,
  최종 선택과 보드 실행 상태를 표시한다.
- [x] 모델 checksum, toolchain version, board status와 deployment artifact checksum을 보고서에 포함한다.

### 품질과 재현

- [x] 현재 남은 Ruff format 8개 파일을 정리한다.
- [x] Ruff lint 2건과 mypy 2건을 해결한다.
- [x] 모든 unit/contract/integration test를 통과시킨다.
- [x] hardware test는 marker로 분리하고, 보드가 없을 때 명시적으로 skip한다.
- [x] 깨끗한 checkout에서 설치→모델 확보→optimize→deploy를 재현한다.
  - tracked source clean archive의 `uv sync --frozen`, CLI, pytest는 재현했다.
  - 2026-08-24 외부 Windows PC에서 모델·vendor 확보, ST Edge AI Core 4.0.1 탐지, MobileNetV2/YOLO26n 단계별 deployment E2E, physical JP2 전환, UART validation까지 재현했다.
  - `arona optimize --deploy` 단일 명령 경로도 MobileNet terminal ArgMax variant로 재현했다.
- [x] 3분 이내 데모 명령과 예상 화면을 `docs/demo.md`에 작성한다.
- [x] 성공 run의 재배포 가능한 metadata/JSON/checksum을 fixture로 고정한다.
  - fixture: `tests/fixtures/deployment/nucleo_checkpoint4_e2e/evidence.json`
- [x] release tag 후보와 제출용 commit을 만든다.

### Day 4 종료 gate

- [x] MobileNetV2 128은 optimize→generate→build→program→validate 전체 성공
- [x] YOLO26n 256 QDQ Int8은 analyze→compile→deploy smoke test 성공
- [x] rewrite 비대상 경로에서도 baseline 유지와 원인이 보고됨
- [x] 테스트·정적 검사 전체 통과
  - external Windows pytest: 50 passed, 1 skipped.
- [x] README의 미구현 주장, 출력 목록, CLI 예시를 실제 동작과 일치시킴

### Commit checkpoint 4

- [x] clean checkout smoke와 전체 품질 gate 통과 후 제출 후보를 커밋한다.
- 권장 메시지: `release: finalize reproducible ARONA MVP demo`

## 8. 리스크와 즉시 대체안

| 리스크 | 판단 시점 | 대체안 |
| --- | --- | --- |
| 로컬 ST Edge AI Core와 공식 모델 기준 버전 불일치 | Day 1 정오 | 로컬 2.2.0에서 먼저 실측하고 실패하면 Core 4.0.0 설치/업데이트를 최우선 처리 |
| QDQ ONNX가 로컬 compiler에서 열리지 않음 | Day 1 오후 | 128 모델의 Int8 QDQ 호환 variant를 사용하고 TFLite frontend는 추가하지 않음 |
| terminal ArgMax 제거가 compiler 지표를 개선하지 않음 | Day 2 오후 | `--expand-softmax`의 실제 차이를 확인하고 둘 다 무효면 “pass-through deployability analyzer”로 정직하게 축소 |
| 카메라/디스플레이 부재 | Day 3 | 고정 input binary와 serial/debug inference 결과로 검증 |
| programming 자동화 실패 | Day 3 | 공식 Model Zoo deployment 명령을 ARONA가 생성·호출하고 그 log를 증거로 보존 |
| YOLO 통합 지연 | Day 3 | YOLO graph 최적화는 생략하되 공식 model-zoo-services 경로의 compile/deploy smoke test는 유지 |
| 실측 latency 수집 불가 | Day 4 | compiler estimate만 별도 표시하고 target 실측값을 생성하지 않음 |

## 9. 제출 증거 체크리스트

- [ ] 모델 원본 URL·라이선스·SHA-256
- [ ] `stedgeai`, STM32CubeProgrammer, compiler, firmware, board revision
- [ ] baseline/optimized 실제 compiler 명령과 원문 log
- [ ] rewrite 적용·거절·원복 기록
- [ ] ONNX Runtime validation 입력 manifest와 결과
- [ ] programming exit code와 생성 artifact checksum
- [ ] 보드 inference log 또는 영상/사진
- [ ] 수치 출처를 구분한 before/after 표
- [ ] 깨끗한 환경 재현 절차

## 10. 공식 근거

- [ST Neural-ART 지원 연산 및 제약](https://stedgeai-dc.st.com/assets/embedded-docs/stneuralart_operator_support.html)
- [ST Edge AI Core CLI](https://stedgeai-dc-qa.st.com/assets/embedded-docs/command_line_interface.html)
- [STM32N6 image classification 배포 절차](https://github.com/STMicroelectronics/stm32ai-modelzoo-services/blob/main/image_classification/docs/README_DEPLOYMENT_STM32N6.md)
- [MobileNetV2 공식 STM32 Model Zoo 정보](https://github.com/STMicroelectronics/stm32ai-modelzoo/blob/main/image_classification/mobilenetv2/README.md)
- [YOLO26n 공식 STM32 Model Zoo 정보](https://github.com/STMicroelectronics/stm32ai-modelzoo/blob/main/object_detection/yolo26n/README.md)



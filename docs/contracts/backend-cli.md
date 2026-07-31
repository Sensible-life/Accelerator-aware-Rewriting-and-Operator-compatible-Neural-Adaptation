# Backend/Pipeline/CLI JSON contract v0.1.0

이 문서는 ARONA backend, optimization pipeline, CLI 및 report generator가 공유하는 Sprint 0
계약을 정의한다. Pydantic 모델인 `src/arona/contracts/v1.py`가 단일 원천이며,
`schemas/v0.1.0/` 아래 JSON Schema는 생성 산출물이다.

## 계약 문서

| JSON Schema | 생산자 | 주요 소비자 | 목적 |
| --- | --- | --- | --- |
| `device-discovery.schema.json` | backend registry | CLI, pipeline | 발견된 장치와 toolchain, 사용 가능 여부 표시 |
| `optimize-request.schema.json` | CLI | optimizer | 모델, target override, 검증 및 최적화 옵션 전달 |
| `run-report.schema.json` | optimizer | CLI, report generator | 실행 상태, 분석, rewrite, 검증, 비교 및 산출물 표현 |

`tests/fixtures/contracts/run-report.sample.json`은 baseline과 최적화 결과가 모두 포함된
CLI/reporting 개발용 예제다. 값에 포함된 compiler 버전과 측정치는 실제 측정값이 아니다.

## 공통 규칙

- 모든 최상위 문서는 `schema_version`을 포함한다.
- 알 수 없는 필드는 오류로 처리한다. 생산자와 소비자의 계약 불일치를 조기에 발견하기
  위한 정책이다.
- 시간은 timezone이 포함된 ISO 8601 문자열로 직렬화한다.
- latency 단위는 millisecond, memory 및 transfer 단위는 byte다.
- ratio는 `0.0` 이상 `1.0` 이하 값이다.
- SHA-256은 소문자 64자리 hexadecimal 문자열이다.
- artifact 경로는 해당 run directory를 기준으로 한 POSIX-style 상대 경로를 권장한다.
- compiler 명령에는 비밀 값이나 전체 환경 변수를 기록하지 않는다.
- 측정할 수 없는 값은 `null`, 아직 생성되지 않은 선택적 결과는 필드 생략 또는
  `null`로 표현한다. 0은 실제 측정값 0일 때만 사용한다.

## 안정적인 식별자

`node_id`는 ONNX node name과 분리된 ARONA 내부 식별자다. node name이 비어 있거나
중복되어도 입력 그래프 내에서 안정적으로 참조할 수 있어야 한다. 최초 import 시
`node_<source_index:04d>` 형태를 기본으로 사용한다. rewrite로 생성된 node는 부모 ID와
rule-local suffix를 조합한다.

`target_id`는 한 discovery 응답 안에서 유일해야 한다. 권장 형식은
`<backend>:<target-family>:<connection-id>`다.

## 상태와 부분 결과

`RunReport`는 최종 보고서뿐 아니라 CLI가 진행 상태와 부분 결과를 저장하는 상태 문서다.
따라서 실행 초반에는 `baseline`, `optimized`, `decision`이 `null`일 수 있다.

완료된 실행에서는 다음 조건을 application layer에서 검증한다.

- `status=completed`이면 `baseline`이 존재한다.
- `decision.selected=optimized`이면 `optimized`가 존재한다.
- 채택된 exact rewrite에는 `validation.status=passed`가 존재한다.
- `graph` 집계 값은 `nodes`와 `partitions` 상세 값과 일치한다.
- artifact 파일은 run directory 밖을 가리키지 않는다.

이 조건들은 여러 필드를 함께 비교해야 하므로 JSON Schema가 아니라 pipeline validation
단계에서 검사한다.

## 호환성 정책

- 선택 필드 추가처럼 기존 소비자가 무시할 수 있는 변경은 minor version 후보지만,
  현재 계약은 알 수 없는 필드를 거부하므로 생산자와 소비자를 함께 갱신한다.
- 필드 삭제, 이름 변경, 의미나 단위 변경은 새로운 version directory와 모델 모듈을 만든다.
- Pydantic 모델 변경 후 `uv run arona schema export`를 실행하고 생성 파일과 fixture 및
  contract test를 같은 commit에 포함한다.

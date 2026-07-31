# Dependency inventory

이 문서는 ARONA가 직접 선택한 패키지의 역할과 버전 관리 정책을 기록한다. 정확한 설치
버전은 `uv.lock`이 단일 원천이며, 아래 resolved version 표는 lockfile을 갱신할 때 같이
갱신한다.

## 관리 도구

| 도구 | 현재 버전 | 역할 |
| --- | --- | --- |
| uv | 0.10.10 | Python 설치, 가상환경, dependency resolution 및 lockfile |
| Python | 3.11.15 | 실행 기준 버전은 3.11 |

## Runtime 직접 의존성

| 패키지 | 버전 범위 | resolved version | 사용 목적 |
| --- | --- | --- | --- |
| NumPy | `>=2.1` | 2.4.6 | tensor fixture 및 수치 비교 |
| ONNX | `>=1.17` | 1.22.0 | 모델 로딩, 검사, shape inference 및 rewrite |
| ONNX Runtime | `>=1.20` | 1.28.0 | 원본·변환 모델 출력 동등성 검증 |
| Pydantic | `>=2.10` | 2.13.4 | backend/pipeline/CLI 계약과 JSON Schema 생성 |
| PyYAML | `>=6.0` | 6.0.3 | 사용자 및 backend 설정 파일 |
| Typer | `>=0.15` | 0.27.0 | CLI |

## Development group

| 패키지 | 버전 범위 | resolved version | 사용 목적 |
| --- | --- | --- | --- |
| Ruff | `>=0.9` | 0.16.0 | lint와 formatter |
| mypy | `>=1.14` | 2.3.0 | 정적 타입 검사 |
| pytest | `>=8.3` | 9.1.1 | 테스트 실행 |
| pytest-cov | `>=6.0` | 7.1.0 | coverage 측정 |
| pre-commit | `>=4.0` | 4.6.1 | commit 전 자동 검사 |

PyTorch는 neural adaptation을 구현할 때 별도 optional extra로 추가한다. Sprint 0에서는
대용량 설치와 불필요한 플랫폼 제약을 피하기 위해 포함하지 않는다. vendor compiler와
SDK는 PyPI 의존성이 아니므로 backend 환경 조사 문서에서 별도로 버전을 고정한다.

위 resolved version은 2026-07-30에 생성한 `uv.lock`을 기준으로 하며, CLI-only MVP 범위에
맞춰 2026-07-31에 UI 전용 dependency를 제거했다.

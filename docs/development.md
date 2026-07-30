# Development setup

ARONA는 Python 및 패키지 환경을 `uv`로 관리한다. 시스템 Python 설치에 의존하지 않으며,
`.python-version`에 지정된 Python 3.11을 uv가 선택하거나 설치한다.

개발 환경을 처음 고정할 때 사용한 uv 버전은 0.10.10이다. lockfile이 재현의 기준이므로
uv의 patch/minor 차이가 있더라도 `--frozen` 설치 결과는 같아야 한다.

## 최초 설정

```bash
uv sync --extra ui
uv run arona version
uv run pytest
```

`uv sync --extra ui`는 CLI/backend 의존성, 로컬 UI 의존성 및 기본 `dev` dependency
group을 설치한다. CI와 재현 실험에서는 lockfile 변경을 막기 위해 다음 명령을 사용한다.

```bash
uv sync --frozen --extra ui
```

## 품질 검사

```bash
uv run ruff format --check .
uv run ruff check .
uv run mypy src
uv run pytest --cov=arona
```

로컬 git hook은 선택적으로 설치한다.

```bash
uv run pre-commit install
uv run pre-commit run --all-files
```

## 의존성 변경

- 직접 의존성과 허용 범위: `pyproject.toml`
- 모든 전이 의존성의 정확한 버전과 hash: `uv.lock`
- Python 기준 버전: `.python-version`
- 사람이 읽는 도구 선택과 현재 direct version: `docs/dependencies.md`

패키지 하나만 검토해 갱신할 때는 다음처럼 실행한다.

```bash
uv lock --upgrade-package onnxruntime
uv sync --extra ui
uv run pytest
```

lockfile은 수동 편집하지 않는다. 의존성 변경 commit에는 `pyproject.toml`, `uv.lock`,
`docs/dependencies.md`와 검증 결과를 함께 반영한다.

## JSON Schema 변경

```bash
uv run arona schema export
uv run pytest tests/test_contracts.py
```

계약 규칙과 versioning은 `docs/contracts/backend-ui.md`를 따른다.

## 저장소 구조

```text
src/arona/
├── cli.py               # Typer CLI 진입점
└── contracts/           # backend/UI Pydantic 계약과 schema exporter
schemas/v0.1.0/          # 생성된 공개 JSON Schema
tests/
├── fixtures/contracts/  # UI와 backend test가 공유하는 예제 JSON
└── test_*.py
docs/
├── backends/            # vendor toolchain 결정과 재현 절차
└── contracts/           # 계약 의미와 호환성 정책
```

추가 구현은 책임별 package(`backends`, `graph`, `pipeline`, `validation`, `reporting`,
`ui`)로 분리하되, vendor SDK 타입이나 원본 compiler JSON을 UI로 직접 노출하지 않는다.
vendor 결과는 항상 `arona.contracts` 모델로 정규화한다.

# GostCheck

Публичный движок автоматизированного нормоконтроля ВКР через GitHub CI/CD
(**PoC v0.1.0**).

Детерминированные правила проверяют LaTeX/PDF/библиографию. LLM даёт только
advisory-замечания. Merge блокирует только formal-gate. Решение о выпуске
принимает нормоконтролёр.

## Быстрый старт (≤15 минут)

Требуется **Python 3.12**.

```powershell
py -3.12 -m venv .venv312
.\.venv312\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.lock
python -m pip install --no-deps -e .
normocontrol --version
normocontrol doctor
python -m pytest -q -m "not live"
```

Linux: `python3.12 -m venv .venv312 && source .venv312/bin/activate` — дальше те же
команды. Подробнее: [docs/setup-windows.md](docs/setup-windows.md),
[docs/setup-linux.md](docs/setup-linux.md).

## Полный прогон и демо

```powershell
# Pass → exit 0
normocontrol run tests/fixtures/demo/pass --provider disabled --out build/demo-pass

# Fail (STR-01) → exit 2
normocontrol run tests/fixtures/demo/fail --provider disabled --out build/demo-fail

# Локальный demo dry-run (без gh/git мутаций)
powershell -ExecutionPolicy Bypass -File demo/run_demo.ps1 -Mode dry-run
```

См. [demo/README.md](demo/README.md).

## Provider flags

| Способ | Пример |
|--------|--------|
| Env | `LLM_PROVIDER=disabled\|ollama\|yandex` |
| CLI | `normocontrol run … --provider disabled` |
| Global | `normocontrol --no-llm run …` |
| Cloud opt-in | `ALLOW_CLOUD_DATA=true` + `LLM_API_KEY` (только Yandex) |

Ключи API только через окружение / GitHub Secrets — не в CLI и не в git.
Документация: [docs/llm-providers.md](docs/llm-providers.md),
[docs/privacy.md](docs/privacy.md).

## Коды выхода (`normocontrol run`)

| Код | Значение |
|----:|----------|
| 0 | Успех или только advisory (warn/info/unverifiable/skipped) |
| 2 | Formal gate fail (блокирующие formal error+fail) |
| 3 | Ошибка конфигурации/входа |
| 4 | Внутренняя/инструментальная ошибка при `--fail-closed` |

LLM/vision **никогда** не возвращают `fail` и не блокируют merge.

## Архитектура (кратко)

```text
build → formal → semantic(advisory) → aggregate(report.json / report.md)
```

- Formal rules → могут блокировать (exit 2).
- Semantic/LLM → только advisory artifact / PR comment.
- CI: required `lint-and-unit` + `formal-gate`; semantic workflow — optional.

Подробнее: [docs/architecture.md](docs/architecture.md),
[docs/github-actions.md](docs/github-actions.md),
[docs/data-flow.md](docs/data-flow.md).

## Состояние проекта

Готово:

- CLI для проверки LaTeX-проекта или PDF с формализованными кодами выхода;
- формальные правила, блокирующий `formal-gate`, JSON- и Markdown-отчёты;
- локальный semantic advisory через Ollama и отключаемые провайдеры;
- unit-, integration-, e2e- и live-тесты, Ruff, strict mypy и CI;
- защита персональных данных: реальные ВКР, отчёты, ключи и локальные настройки
  исключены из git.

До релизной приёмки необходимо:

- устранить ложные срабатывания PDF-проверок шрифта и нижнего поля на реальных ВКР;
- закрыть расхождения эталонного formal-корпуса для `BIB-03`, `BIB-04`,
  `REV-02`, `REV-03` и `REV-04`;
- реализовать оставшиеся semantic-правила, обозначенные как `not_implemented`;
- подключить безопасный workflow проверки реальной ВКР в приватном репозитории или
  на self-hosted runner;
- после исправлений повторить приёмочный прогон на контрольных PDF.

Подробные задания, тесты, corner cases и Git-команды собраны в
[docs/remediation-prompts.md](docs/remediation-prompts.md).

## Границы автоматизации

**Делает:** формальный gate, отчёты, PR-comment, advisory semantic (opt-in).  
**Не делает:** авто-merge без человека, хранение реальных ВКР в git, «оценку»
исторических работ по draft-рубрике 2026 как юридический вердикт.

## Документация

| Документ | Тема |
|----------|------|
| [CONTRIBUTING.md](CONTRIBUTING.md) | Ветки, PR, review |
| [SECURITY.md](SECURITY.md) | Угрозы, секреты, runner |
| [CHANGELOG.md](CHANGELOG.md) | История релизов |
| [docs/acceptance.md](docs/acceptance.md) | Чеклист v0.1.0 + tag |
| [docs/remediation-prompts.md](docs/remediation-prompts.md) | Промпты и Git-команды для устранения выявленных пробелов |
| [docs/troubleshooting.md](docs/troubleshooting.md) | Симптомы → действия |
| [docs/privacy.md](docs/privacy.md) | Персональные данные |

## Release check

```powershell
python scripts/release_check.py --out build/release-check.json
```

## Ответственность

- Тимур: каркас, rubric, extract, LLM, semantic, GPU benchmark.
- Доминик: formal rules, PDF, bibliography, fixtures и метрики.
- Араик: orchestrator, reporting, GitHub workflows, demo и документация.

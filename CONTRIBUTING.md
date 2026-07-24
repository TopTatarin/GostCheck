# Contributing

## Ветки и PR

1. Работайте от актуального `main` в feature-ветке (`feat/...`).
2. Не пушьте напрямую в `main`.
3. PR review: минимум **1** approving review; conversations resolved.
4. Required checks: `lint-and-unit`, `formal-gate`.
5. **Не** делайте required: `build-latex`, `publish-report`, любые `semantic-*`.

Reviewer по ролям: изменения formal rules → Доминик/Тимур; orchestrator/CI/docs →
Тимур как reviewer PR Араика (по плану).

## Локальные проверки перед PR

```powershell
python -m ruff format --check .
python -m ruff check .
python -m mypy src
python -m pytest -q -m "not live"
python scripts/release_check.py --out build/release-check.json
```

## Контракты, которые нельзя ломать молча

- Formal может `fail` / exit 2; LLM — только advisory.
- Секреты, PDF студентов, ФИО — не в git (`samples/private/` только локально).
- Изменения `rubric.yaml` — отдельный commit + тест миграции.
- Unit-тесты без сети; `live` marker выключен по умолчанию.

## Сообщения commit

Кратко, в стиле репозитория: `feat|fix|docs|ci(scope): why`.

Примеры: `ci(github): enforce formal gate and publish report`,
`docs(release): finalize security runbooks and v0.1 acceptance`.

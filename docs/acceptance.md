# Acceptance checklist — v0.1.0

Подпишите (имя / дата) после зелёного `main` и review.

## Функциональность

- [ ] `normocontrol run tests/fixtures/demo/pass --provider disabled` → exit **0**
- [ ] `normocontrol run tests/fixtures/demo/fail --provider disabled` → exit **2**
- [ ] `demo/run_demo.ps1 -Mode dry-run` (или `.sh`) → pass/fail/fixed OK
- [ ] PR comment marker `<!-- normocontrol-report -->` на demo PR
- [ ] Semantic jobs **не** required в branch protection

## Качество

- [ ] `python scripts/release_check.py --out build/release-check.json` → `"ok": true`
- [ ] `python -m pytest -q` зелёный
- [ ] `ruff format --check .` / `ruff check .` / `mypy src` зелёные
- [ ] `python scripts/evaluate_semantic.py --provider mock` → все три semantic rate равны 1.0
- [ ] Coverage ≥ 85% в CI

## Безопасность / приватность

- [ ] Нет tracked student PDF / API keys
- [ ] `benchmark-results/` не tracked; semantic corpus содержит только synthetic-текст
- [ ] `git grep` на секреты / `C:\Users\` / `samples/private/*.pdf` — пусто
- [ ] LICENSE: внешний LaTeX-класс не публиковать шире, чем разрешила кафедра
      (MIT репозитория ≠ лицензия чужого `.cls`, если статус неизвестен)

## Branch protection

- [ ] PR review ≥ 1, conversations resolved, branch up to date
- [ ] Required: `lint-and-unit`, `formal-gate` only
- [ ] Fallback, если Rulesets недоступны: classic protection + manual review
      discipline зафиксирована в SECURITY.md

## Tag (только после merge)

Команды **подготовить**, выполнять владельцу **после** merge в `main` и
подписанного чеклиста — **не** из `release_check.py`:

```bash
git switch main
git pull --ff-only
git tag -a v0.1.0 -m "GostCheck PoC v0.1.0"
# git push origin v0.1.0   # только после явного решения команды
```

**Не** пушьте tag автоматически из CI этой задачи.

## Подписи

| Роль | Имя | Дата |
|------|-----|------|
| Араик (docs/release) | | |
| Reviewer | | |
| Нормоконтролёр (demo) | | |

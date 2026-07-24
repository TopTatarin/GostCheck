# Security

## Модель угроз (кратко)

| Угроза | Мера |
|--------|------|
| Недоверенный текст ВКР / prompt injection | LLM только advisory; цитаты сверяются с chunks; raw thesis не в логах |
| Утечка секретов | API keys только env/GitHub Secrets; redaction в логах; нет ключей в CLI argv |
| Self-hosted GPU runner | Только `workflow_dispatch` на `main` + environment approval; нет `pull_request` на GPU |
| Подмена ref/SHA | Semantic checkout всегда `ref: main`; нет input SHA |
| Fork PR | Minimal `contents: read`; publish comment degrade to neutral без write |
| Retention | Artifacts GitHub — по политике org; локальные `build/` / `samples/private/` не коммитить |

## Что нельзя коммитить

- `YANDEX_AI_API_KEY`, `LLM_API_KEY`, `.env`
- Реальные PDF/DOC студентов, отчёты с ПДн
- Абсолютные home-пути с именами пользователей в tracked-файлах

Проверка:

```bash
git grep -n -E '(YANDEX_AI_API_KEY=.+|samples/private/.+\.pdf|C:\\Users\\)' -- ':!docs/*example*' || true
```

## Сообщить об уязвимости

Откройте private security advisory в GitHub или напишите maintainers из
`.github/CODEOWNERS`. Не публикуйте эксплойты и студенческие данные в issues.

## Branch protection (ручная настройка)

Settings → Branches → rule for `main`:

1. Require a pull request before merging; **1** approval; dismiss stale reviews.
2. Require conversation resolution.
3. Require status checks: **`lint-and-unit`**, **`formal-gate`**; require branch up to date.
4. Do **not** require semantic jobs.
5. Restrict who can push to matching branches (по возможности).

Если plan/роль не даёт Rulesets — используйте классический branch protection и
дисциплину manual review (см. [docs/acceptance.md](docs/acceptance.md)).

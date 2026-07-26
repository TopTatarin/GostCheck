# Privacy

## Принципы

1. В git только код, синтетические fixtures, рубрика и документация.
2. Реальные ВКР, ФИО, оценки, цитаты из работ студента — **локально**
   (`samples/private/`, `build/`), никогда в remote.
3. Логи redacted: нет API keys и длинного текста ВКР.
4. Cloud (Yandex) — только opt-in `ALLOW_CLOUD_DATA=true` + approval environment.

Реальную ВКР храните только в закрытом репозитории (private thesis repository)
или защищённом хранилище (protected submission store) с минимально необходимым
доступом. Публичный репозиторий GostCheck (public GostCheck repository) должен
содержать только движок, reusable workflow/action, документацию и синтетические
fixtures; не копируйте в него PDF, LaTeX-исходники студента, ФИО или отчёты
проверки.

Private consumer repository вызывает публичный reusable workflow по
проверенному commit SHA или release tag. Выдавайте минимальные permissions:
`contents: read` для checkout и, только если нужен PR comment,
`pull-requests: write`. При `provider: disabled` текст не отправляется
семантическому провайдеру.

## Локальные private samples

```text
samples/private/          # tracked: .gitkeep + .gitignore only
  anisimova.pdf           # local only
  zoloev.pdf              # local only
```

Baseline demo помечает отчёты как **exploratory / legacy-input** и не утверждает,
что исторические работы обязаны соответствовать draft-рубрике 2026.

## Retention

- GitHub Actions artifacts: по политике организации (удаляйте вручную при необходимости).
- Consumer artifact содержит отчёты и технические diagnostics, но не исходный PDF
  или дерево LaTeX. Настройте минимальный допустимый retention в private repository.
- Не храните production thesis PDF на self-hosted runner дольше прогона; чистите
  workspace между jobs.

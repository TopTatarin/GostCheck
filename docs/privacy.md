# Privacy

## Принципы

1. В git только код, синтетические fixtures, рубрика и документация.
2. Реальные ВКР, ФИО, оценки, цитаты из работ студента — **локально**
   (`samples/private/`, `build/`), никогда в remote.
3. Логи redacted: нет API keys и длинного текста ВКР.
4. Cloud (Yandex) — только opt-in `ALLOW_CLOUD_DATA=true` + approval environment.

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
- Не храните production thesis PDF на self-hosted runner дольше прогона; чистите
  workspace между jobs.

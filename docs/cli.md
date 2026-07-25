# CLI: `normocontrol run`

Полный прогон нормоконтроля одной командой:

```text
build → formal → semantic → aggregate
```

## Синтаксис

```bash
normocontrol run PATH \
  --config normocontrol.yaml.example \
  --rubric rubric.yaml \
  --out build/normocontrol \
  [--profile software|research|organizational] \
  [--provider disabled|ollama|yandex] \
  [--only STAGE_OR_PREFIX ...] \
  [--final] \
  [--fail-closed] \
  [--no-llm]
```

`PATH` — каталог с `main.tex` / `main.pdf` или файл `.tex` / `.pdf`.

Глобальный флаг `--no-llm` отключает semantic-провайдер независимо от env.

## Коды выхода

| Код | Значение |
|----:|----------|
| 0 | Успех или только неблокирующие advisory-результаты |
| 1 | Ошибка выполнения команды вне formal gate (зарезервированный публичный runtime-код) |
| 2 | Formal gate fail: `error+fail` либо блокирующий `error+unverifiable` |
| 3 | Ошибка конфигурации/входа (нет файла, неизвестный `--only`/`--profile`, lock) |
| 4 | Внутренняя/инструментальная ошибка при `--fail-closed` |

LLM/vision **никогда** не переводят прогон в код `2`.

Для PDF-only входа FMT-01/02/03/05 выполняются по текстовому слою и геометрии
PyMuPDF. FMT-04 может быть блокирующим `unverifiable`, поскольку абзацный отступ
нельзя надёжно доказать по PDF. PDF без text layer возвращает `2`; повреждённый,
зашифрованный или отсутствующий PDF отклоняется как ошибка входа с кодом `3`.

## `--only`

- Стадии: `build`, `formal`, `semantic`, `aggregate`
- Префиксы правил: `STR`, `ANN`, `SYS-01`, …
- Неизвестный токен → exit `3`

## `--final`

Явно применяет `severity_final` из рубрики (например `ANN-03`, `REV-01`). Без флага draft-severity не повышается.

## Артефакты `--out`

```text
out/
  report.json            # published schema v1.2 (header/counts/findings)
  report.md              # Markdown с marker <!-- normocontrol-report -->
  summary.json           # GitHub-friendly summary + counts/gate
  run_state.json
  stages/{build,formal,semantic,aggregate}.json
  cache/...
  canceled.json          # только при Ctrl+C
```

`report.json` всегда публикуется, в том числе при formal fail. Рендерер **не** меняет gate.
`header.generated_at` содержит фактическое время текущего aggregate-запуска в UTC
с точностью до секунд (`YYYY-MM-DDTHH:MM:SSZ`), включая запуски с cache hit.
`header.degraded=true` означает, что обязательная formal-проверка осталась
неполной; число таких блокирующих результатов вынесено в
`counts.blocking_unverifiable` и показывается в Markdown/summary. Advisory
LLM/vision `unverifiable` в этот счётчик не входят и сами по себе не включают
degraded mode.

Запись стадий атомарна. Повторный запуск с тем же входом использует cache hit; смена rubric/config/tool/model инвалидирует ключ. LLM-cache изолирован по `model_hash`.

## Примеры

```bash
# Детерминированный demo pass
normocontrol run tests/fixtures/demo/pass --no-llm --out build/pass

# Только formal-стадия
normocontrol run tests/fixtures/demo/pass --no-llm --only formal --out build/formal-only

# Финальный прогон с severity_final
normocontrol run tests/fixtures/demo/pass --no-llm --final --out build/final
```

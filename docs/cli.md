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

## Резюме запуска

После каждого `normocontrol run` CLI печатает компактное резюме:

```text
GostCheck run summary
input: tests/fixtures/demo/pass
profile: software
provider: disabled
gate: PASS
degraded: false
degraded_reason: none
counts: pass=… fail=… warn=… info=… not_applicable=… unverifiable=… skipped=…
blocking_findings: 0
report.md: build/demo-pass/report.md
report.json: build/demo-pass/report.json
exit_code: 0 (success; advisory findings do not block)
```

`blocking_findings` содержит только количество и `rule_id`, без текста документа и
evidence. Для `degraded=true` поле `degraded_reason` перечисляет formal-правила,
оставшиеся `unverifiable`. При ошибках входа/конфигурации и внутренних ошибках
резюме также печатается с `gate: FAIL`, кодом `3` или `4` и пометкой
`(not generated)` у отсутствующих отчётов.

Путь внутри текущего checkout показывается относительно него. Внешний абсолютный
путь безопасно сокращается до `…/<имя>`: пользовательские каталоги, prompts,
responses, API-ключи и полный текст ВКР в консоль не выводятся.

Display paths нормализуются в Unicode NFC только для консоли: имя исходного файла
на диске не переименовывается. Если текущая кодировка stdout/stderr (например,
CP1251 при перенаправлении на Windows) не представляет отдельные символы, CLI
показывает их через безопасные `\uNNNN`/`\UNNNNNNNN` escape-последовательности.
Ошибка печати резюме не меняет уже вычисленный код `0` или `2`.

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
`report.json` и другие JSON-файлы в `--out` всегда записываются как UTF-8,
независимо от кодировки консоли.
`header.generated_at` содержит фактическое время текущего aggregate-запуска в UTC
с точностью до секунд (`YYYY-MM-DDTHH:MM:SSZ`), включая запуски с cache hit.
`header.degraded=true` означает, что обязательная formal-проверка осталась
неполной; число таких блокирующих результатов вынесено в
`counts.blocking_unverifiable` и показывается в Markdown/summary. Advisory
LLM/vision `unverifiable` в этот счётчик не входят и сами по себе не включают
degraded mode.

Запись стадий атомарна. Повторный запуск с тем же входом использует cache hit; смена rubric/config/tool/model инвалидирует ключ. LLM-cache изолирован по `model_hash`.

## Метрики formal-корпуса

```bash
python scripts/evaluate_formal_fixtures.py
```

Помимо общей confusion matrix команда печатает для каждого formal `rule_id`:
`expected`, `actual`, `TP`, `FP`, `FN`, `TN`, `precision`, `recall`, `F1`,
числа `unverifiable`/`not_applicable` и `mismatches`. Formal-правило, которого
нет в corpus, всё равно присутствует в выводе с нулевыми counts и метриками
`0.000`; это делает пробел покрытия явным. Эти данные относятся к синтетическому
evaluation corpus и поэтому не добавляются в публичный `report.json` одного
пользовательского запуска. Schema v1.2 и старые snapshots остаются совместимыми.
`expected` — число положительных labels (`fail`/`warn`/`detect`), `actual` —
число fixture-rule пар, где движок действительно выдал `fail` или `warn`.

## Примеры

```bash
# Детерминированный demo pass
normocontrol run tests/fixtures/demo/pass --no-llm --out build/pass

# Только formal-стадия
normocontrol run tests/fixtures/demo/pass --no-llm --only formal --out build/formal-only

# Финальный прогон с severity_final
normocontrol run tests/fixtures/demo/pass --no-llm --final --out build/final
```

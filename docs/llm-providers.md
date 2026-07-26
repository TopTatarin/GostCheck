# LLM providers

LLM в GostCheck выполняет только консультативные проверки. Ошибка модели, сети или схемы
возвращает `unverifiable`, явно отключённый режим — `skipped`; эти результаты не блокируют
merge и не создают `fail`.

## Конфигурация

Настройки читаются из секции `llm` YAML-конфига и окружения. Приоритет:
`--no-llm` → явные CLI-параметры → окружение → YAML → безопасные defaults.
Команды `run`, `semantic` и `llm doctor` принимают `--provider`, `--model` и
`--base-url` (где применимо); API-ключ остаётся только в окружении.

| Переменная | Назначение | Ollama по умолчанию |
| --- | --- | --- |
| `LLM_PROVIDER` | `ollama`, `yandex` или `disabled` | `disabled` |
| `LLM_BASE_URL` | OpenAI-совместимый `/v1` endpoint | `http://127.0.0.1:11434/v1` |
| `LLM_MODEL` | Имя модели или Yandex model URI | `qwen3:8b-q4_K_M` |
| `LLM_API_KEY` | Секрет; пустое значение допустимо только для Ollama | `ollama` |
| `LLM_TIMEOUT` | Тайм-аут запроса в секундах | `60` |
| `LLM_MAX_CONCURRENCY` | Число одновременных запросов | `1` |
| `LLM_NUM_CTX` | Контекст Ollama в токенах | `8192` |
| `LLM_MAX_OUTPUT_TOKENS` | Максимум токенов ответа | `512` |
| `ALLOW_CLOUD_DATA` | Явное разрешение отправки данных в облако | `false` |

API-ключи задаются только через окружение и никогда не передаются флагом CLI, чтобы они не
попали в историю shell или список процессов. Не добавляйте `.env` в git.
Значения `LLM_NUM_CTX` и `LLM_MAX_OUTPUT_TOKENS` валидируются; профиль больше 8192/512 —
явный opt-in, который нужно заново проверить на целевой GPU.

## Ollama

Профиль использует единый URL `http://127.0.0.1:11434/v1`. Явный IPv4 loopback обходит
Windows-конфигурации, где `localhost` сначала разрешается в IPv6. Для локального structured
output provider сопоставляет этот URL с native `/api/chat`: так Ollama гарантированно применяет
`think: false`, `temperature=0`, `num_ctx=8192`, `num_predict=512`, non-streaming и JSON Schema.
Ответ повторно валидируется исходной Pydantic-схемой с запретом неизвестных полей.
Локальный клиент игнорирует `HTTP_PROXY`/`HTTPS_PROXY`; CLI override `--base-url` остаётся
приоритетнее окружения.

Semantic prompt разрешает модели ссылаться только на переданные `chunk_id`. Каждая
`evidence.quote` должна быть точной непрерывной подстрокой соответствующего `text`: нельзя
менять регистр, пунктуацию, пробелы или `е/ё`, склеивать фрагменты и использовать многоточие.
Канонически эквивалентные NFC/NFD-представления Unicode принимаются. Модель не возвращает
locator — GostCheck вычисляет точный диапазон цитаты после проверки.
Чтобы ответы с шестью element-level цитатами укладывались в существующий лимит 512 токенов,
внутренний LLM-wire использует короткие Pydantic aliases. Это не меняет публичные имена
`rule_id`, `status`, `confidence`, `summary`, `evidence` и `elements`: после повторной строгой
валидации отчёт сериализуется с прежними полями.

```powershell
$env:LLM_PROVIDER = "ollama"
normocontrol llm doctor
normocontrol run tests/fixtures/demo/pass --config normocontrol.yaml.example `
  --provider ollama --model qwen3:8b-q4_K_M `
  --base-url http://127.0.0.1:11434/v1
```

`llm doctor` сначала вызывает `/models`, затем делает минимальный synthetic schema-probe.
Диагностика отдельно сообщает `endpoint is unavailable`, `configured model is not available`
или `strict JSON schema capability is unavailable`. Все три состояния отображаются как
`UNVERIFIABLE` и не меняют успешный код завершения диагностической команды; только доступные
daemon, модель и строгая схема дают `status=OK`.

## Synthetic semantic evaluation

Версионированный corpus `tests/fixtures/semantic/corpus.json` содержит только вымышленные
данные и три полноценных документа: positive, warning и insufficient. Для каждого документа
есть аннотация, введение, постановка задачи, основной раздел, анализ результатов и заключение;
каждое из шести реализованных правил имеет все три класса.

Воспроизводимый offline-run не обращается к сети:

```powershell
python scripts/evaluate_semantic.py --provider mock
```

Результат записывается в игнорируемый каталог
`benchmark-results/semantic-evaluation.json`. В отчёте нет текста документов, цитат,
ответов модели, абсолютных путей или времени запуска. Для каждого правила публикуются:

- `schema_valid_rate` — доля наблюдений без schema/provider/section diagnostic после не более
  чем одной repair-попытки;
- `evidence_valid_rate` — доля наблюдений со строгими подтверждёнными цитатами
  (для actionable-классов цитата обязательна);
- `useful_advisory_rate` — доля positive/warning случаев, давших проверяемый
  `pass`/`warn`/`info`.

Локальная live-оценка является opt-in, использует только этот corpus и после теста вызывает
`ollama stop`:

```powershell
$env:RUN_LLM_LIVE = "1"
python -m pytest -q -m live tests/live/test_semantic_corpus.py
```

Semantic wrapper различает `section_missing`, `invalid_schema`, `invalid_evidence`,
`provider_timeout`, `provider_error` и `provider_disabled`. Все эти исходы остаются
консультативными и не создают `fail`.

## Yandex AI Studio

Endpoint по умолчанию — `https://ai.api.cloud.yandex.net/v1`. URI модели задаётся через
YAML, `LLM_MODEL` или `--model`; ключ обязателен в окружении. Облачный вызов запрещён,
пока `ALLOW_CLOUD_DATA=true` не задан явно.

```powershell
$env:LLM_PROVIDER = "yandex"
$env:LLM_MODEL = "gpt://<folder-id>/<model>/latest"
$env:LLM_API_KEY = "<secret>"
$env:ALLOW_CLOUD_DATA = "true"
normocontrol llm doctor
```

## Retry и fallback

Повторяются только тайм-ауты, HTTP 429 и HTTP 5xx: не более четырёх попыток и 30 секунд суммарно,
с exponential backoff, jitter и поддержкой `Retry-After`. Ошибки аутентификации и другие 4xx не
повторяются. Локальный CPU fallback выполняет Ollama. Cloud fallback разрешается только при
наличии настроенного Yandex-провайдера и явной политике `ALLOW_CLOUD_DATA=true`; иначе результат
остаётся `unverifiable`.

Для полного отключения используйте любой вариант:

```powershell
$env:LLM_PROVIDER = "disabled"
normocontrol llm doctor --provider disabled
normocontrol --no-llm llm doctor
```

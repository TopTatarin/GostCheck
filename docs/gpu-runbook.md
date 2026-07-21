# GPU/CPU runbook для Ollama и воспроизводимый LLM benchmark

Этот runbook проверяет локальный профиль `qwen3:8b-q4_K_M` на RTX 4070 Super, но не
делает GPU обязательным. Семантический результат остаётся консультативным: допустимы только
`warn`, `info`, `not_applicable` и `unverifiable`; `fail` схемой запрещён.

## Зафиксированный профиль

- Python 3.12, Ollama и `qwen3:8b-q4_K_M`;
- рекомендуемый `num_ctx=8192`;
- `max_concurrency=1`;
- `max_output_tokens=512`;
- один warming pass перед измеряемым запросом;
- не более одного измеряемого запроса одновременно.

Контекст 40K не считается гарантированно помещающимся в 12 ГБ VRAM. При OOM сначала закройте
другие GPU-процессы, затем уменьшите `--num-ctx`; эталонным и рекомендуемым остаётся 8192.
`benchmark/baseline.example.json` показывает только форму записи и не является заявленной
производительностью конкретной машины.

## GPU smoke на Windows

```powershell
ollama pull qwen3:8b-q4_K_M
powershell -ExecutionPolicy Bypass -File scripts/smoke_ollama.ps1
python scripts/benchmark_llm.py --provider ollama --model qwen3:8b-q4_K_M --fixture tests/fixtures/semantic/complete/bundle.json
```

Smoke проверяет `nvidia-smi`, версию Ollama, наличие модели, `ollama ps` до и после одного
schema-запроса на русском. Отсутствие `nvidia-smi` допускается для CPU. Драйвер NVIDIA ниже
рекомендуемой ветки 531.x даёт предупреждение. Если GPU обнаружен, а `ollama ps` показывает
`100% CPU`, результат нельзя записывать как GPU baseline. Частичная загрузка отображается как
`mixed` с долями CPU/GPU.

Benchmark обращается к tray daemon через `http://127.0.0.1:11434`: явный IPv4 loopback обходит
конфигурации Windows, где `localhost` разрешается в IPv6, а Ollama слушает только IPv4.

Обычный benchmark делает warming pass и затем измеряемый запрос. Время измеряется монотонными
часами. JSON атомарно записывается в `benchmark-results/last.json`, а при Ctrl+C незавершённый
файл не публикуется. Запись содержит только метаданные GPU/VRAM, processor split, digest модели,
SHA-256 промпта, токены, latency, tokens/sec и результат проверки схемы. Текст fixture, ответ
модели и API-ключ в неё не попадают. Если провайдер не вернул usage, поля токенов и tokens/sec
имеют значение `null`.

Для привязки результата к конкретным весам можно передать полный digest из `ollama list`:

```powershell
python scripts/benchmark_llm.py --provider ollama --model qwen3:8b-q4_K_M --fixture tests/fixtures/semantic/complete/bundle.json --expected-digest <64-hex-digest>
```

## Принудительный CPU

Переменная должна применяться к daemon, поэтому уже запущенный tray Ollama сначала нужно
остановить. Команда `--force-cpu` проверяет это условие и, если оно не выполнено, печатает ту же
инструкцию вместо неоднозначного GPU/CPU результата.

В первом PowerShell:

```powershell
Stop-Process -Name ollama -ErrorAction SilentlyContinue
$env:CUDA_VISIBLE_DEVICES = "-1"
ollama serve
```

Во втором PowerShell:

```powershell
$env:CUDA_VISIBLE_DEVICES = "-1"
python scripts/benchmark_llm.py --provider ollama --model qwen3:8b-q4_K_M --fixture tests/fixtures/semantic/complete/bundle.json --force-cpu
```

Если порт 11434 уже занят, не запускайте второй daemon: найдите и остановите tray-процесс.
Для CPU-профиля требуется не менее 12 ГиБ физической RAM. После запроса `ollama ps` должен
показать `100% CPU`; GPU placement при `--force-cpu` считается ошибкой проверки.

## Yandex fallback: только synthetic и только opt-in

Cloud benchmark заблокирован без обоих условий: явного `--allow-cloud` и `LLM_API_KEY` в
окружении. Дополнительно policy guard разрешает только tracked synthetic fixture
`tests/fixtures/semantic/complete/bundle.json`. Другой путь, изменённый текст или источник без
префикса `synthetic/` блокируется, поэтому реальная ВКР не может случайно уйти в облако.

```powershell
$env:LLM_MODEL = "gpt://<folder-id>/<model>"
$env:LLM_API_KEY = "<secret>"
python scripts/benchmark_llm.py --provider yandex --fixture tests/fixtures/semantic/complete/bundle.json --allow-cloud
```

Ключ не передаётся аргументом CLI, не логируется и не сохраняется в benchmark JSON.

## Live-тест

По умолчанию marker `live` исключён общей конфигурацией pytest. На машине с Ollama его можно
включить явно:

```powershell
$env:RUN_LLM_LIVE = "1"
python -m pytest -q -m live tests/live/test_ollama_qwen3.py
```

Если daemon или модель отсутствуют, live-тест делает `skip`, а не `fail`. Unit-тесты не делают
сетевых запросов и используют `httpx.MockTransport`.

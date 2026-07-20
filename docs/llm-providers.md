# LLM providers

LLM в GostCheck выполняет только консультативные проверки. Ошибка модели, сети или схемы
возвращает `unverifiable`, явно отключённый режим — `skipped`; эти результаты не блокируют
merge и не создают `fail`.

## Конфигурация

Настройки читаются из окружения. Явные CLI-параметры имеют приоритет над окружением, а
глобальный `--no-llm` имеет приоритет над всеми остальными значениями.

| Переменная | Назначение | Ollama по умолчанию |
| --- | --- | --- |
| `LLM_PROVIDER` | `ollama`, `yandex` или `disabled` | `disabled` |
| `LLM_BASE_URL` | OpenAI-совместимый `/v1` endpoint | `http://localhost:11434/v1` |
| `LLM_MODEL` | Имя модели или Yandex model URI | `qwen3:8b-q4_K_M` |
| `LLM_API_KEY` | Секрет; пустое значение допустимо только для Ollama | `ollama` |
| `LLM_TIMEOUT` | Тайм-аут запроса в секундах | `60` |
| `LLM_MAX_CONCURRENCY` | Число одновременных запросов | `1` |
| `ALLOW_CLOUD_DATA` | Явное разрешение отправки данных в облако | `false` |

API-ключи задаются только через окружение и никогда не передаются флагом CLI, чтобы они не
попали в историю shell или список процессов. Не добавляйте `.env` в git.

## Ollama

Профиль использует `http://localhost:11434/v1`, `temperature=0`, non-streaming JSON Schema
output и `reasoning_effort: "none"`. Ollama сам выбирает GPU, а при его отсутствии выполняет
модель на CPU; отдельной GPU-настройки GostCheck не требует.

```powershell
$env:LLM_PROVIDER = "ollama"
normocontrol llm doctor
```

`llm doctor` вызывает `/models`. Выключенный daemon или отсутствующая модель отображаются как
`UNVERIFIABLE` и не меняют успешный код завершения диагностической команды.

## Yandex AI Studio

Endpoint по умолчанию — `https://ai.api.cloud.yandex.net/v1`. URI модели и ключ обязательны в
окружении. Облачный вызов запрещён, пока `ALLOW_CLOUD_DATA=true` не задан явно.

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

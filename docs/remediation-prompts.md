# Промпты для доведения GostCheck до релизной готовности

Документ содержит независимые задания для исправления проблем, выявленных после объединения
основных веток. Каждый промпт рассчитан на отдельную ветку и отдельный Pull Request.

Не выполняйте несколько заданий в одной ветке. Следующее задание начинайте только после слияния
предыдущего PR и обновления локального `main`.

## Общие правила для всех заданий

Перед передачей любого промпта исполнителю добавьте к нему этот блок:

```text
Работай только внутри репозитория GostCheck:
E:\GostCheck\repository\GostCheck

Сначала изучи существующую реализацию, тесты, публичные схемы и документацию. Не удаляй и не
переименовывай существующие правила рубрики, поля severity_final, fixtures, публичные CLI-флаги
или коды выхода без отдельного обоснования и миграционных тестов.

Не используй реальные ВКР в тестах и не копируй их в репозиторий. Все новые fixtures должны
быть синтетическими. Не добавляй API-ключи, .env, абсолютные пользовательские пути, содержимое
локальных отчётов, build/ или benchmark-results/.

Не выполняй git reset --hard, git clean, git checkout --, force push, удаление веток, amend
чужих коммитов или автоматический merge. Не изменяй файлы вне указанного scope. Если для
решения требуется новый production dependency, сначала докажи необходимость; по возможности
используй уже установленные библиотеки.

Код должен работать на Python 3.12, проходить strict mypy, Ruff и существующие тесты.
Обязательно добавь unit-тесты, нужные integration/e2e-тесты и corner cases. Не ослабляй тесты,
схемы, evidence validation, формальный gate или правила приватности ради зелёного результата.

Перед коммитом покажи:
1. git status --short;
2. git diff --check;
3. git diff --name-status;
4. результаты всех указанных тестов;
5. git diff --cached --name-status после staging.

Если обнаружишь противоречие требований, остановись до изменения публичного контракта и
опиши варианты. Не выбирай молча самый удобный вариант.
```

## Работа в Git Bash

Команды ниже предназначены для Git Bash. Они не открывают интерактивный pager:

```bash
cd /e/GostCheck/repository/GostCheck
export GIT_PAGER=cat
export PAGER=cat

# Активируй существующую Python 3.12-среду.
if [ -f .venv/Scripts/activate ]; then
  source .venv/Scripts/activate
elif [ -f .venv312/Scripts/activate ]; then
  source .venv312/Scripts/activate
else
  echo "Virtualenv not found. Create it with: py -3.12 -m venv .venv"
  exit 1
fi

python --version
```

Ожидаемый результат:

```text
Python 3.12.x
```

Если Git всё же показывает длинный текст в отдельном окне, нажмите `q`. В приведённых ниже
командах используется `--no-pager`, поэтому обычно этого окна не будет.

---

## Промпт 1. Форматирование и обязательный format-check в CI

### Текст промпта

```text
Исправь релизную гигиену GostCheck.

Scope:
- Python-файлы, которые реально изменит `python -m ruff format .`;
- `.github/workflows/ci.yml`;
- `.github/workflows/normocontrol.yml`;
- `scripts/release_check.py`, только если его поведение расходится с документированным
  acceptance contract;
- тесты контракта workflow и release check.

Требуется:
1. Запусти `python -m ruff format .` и не вноси параллельно смысловых изменений.
2. Добавь `python -m ruff format --check .` в оба quality-пути GitHub Actions до Ruff lint.
3. Сохрани `ruff check`, strict mypy, pytest и coverage >=85%.
4. Убедись, что `scripts/release_check.py` выполняет все те же обязательные проверки, что
   перечислены в `docs/acceptance.md`.
5. Не изменяй snapshots и ожидаемые результаты правил только из-за форматирования.

Обязательные тесты:
- расширь `tests/unit/test_workflow_normocontrol.py`: workflow содержит отдельный
  `ruff format --check .`, затем `ruff check`, mypy и pytest;
- расширь `tests/unit/test_docs_contract.py`: acceptance checklist и release-check не
  расходятся по обязательным quality-командам;
- если менялся `release_check.py`, добавь unit-тест успешного набора стадий и тест остановки
  на format failure.

Corner cases:
- форматирование не должно затронуть YAML, JSON fixtures и `rubric.yaml`;
- CI должен завершаться ошибкой при неформатированном Python-файле;
- lint и format являются разными проверками и не заменяют друг друга;
- команды должны одинаково работать на Windows Python 3.12 и Ubuntu runner.

Ожидаемый результат:
- `ruff format --check .` возвращает exit 0;
- `release_check.py` возвращает `"ok": true`;
- полный pytest зелёный;
- coverage остаётся не ниже 85%;
- в diff нет смысловых изменений formal/semantic логики.
```

### Ветка, проверка и выгрузка

```bash
git switch main
git pull --ff-only
git switch -c fix/release-format-gate

# После выполнения промпта:
python -m ruff format --check .
python -m ruff check .
python -m mypy src
python -m pytest -q
python scripts/release_check.py --out build/release-check-format.json

git status --short
git diff --check
git --no-pager diff --name-status
git --no-pager diff --stat

git add -- \
  .github/workflows/ci.yml \
  .github/workflows/normocontrol.yml \
  demo scripts src tests

git --no-pager diff --cached --name-status
git --no-pager diff --cached --check
git commit -m "fix(ci): enforce release formatting gate"
git push -u origin HEAD

gh pr create \
  --base main \
  --head fix/release-format-gate \
  --title "fix(ci): enforce release formatting gate" \
  --body "Adds Ruff format enforcement and aligns CI with the release checklist."

gh pr checks --watch
```

Ожидаемый результат Git:

```text
[fix/release-format-gate <hash>] fix(ci): enforce release formatting gate
branch 'fix/release-format-gate' set up to track 'origin/fix/release-format-gate'
https://github.com/TopTatarin/GostCheck/pull/<номер>
All checks were successful
```

---

## Промпт 2. PDF-only formal checks и запрет ложного PASS

### Текст промпта

```text
Исправь PDF-only путь GostCheck так, чтобы полноценный PDF с текстовым слоем действительно
проверялся, а десятки обязательных `unverifiable` не превращались в обычный PASS.

Используй существующие PyMuPDF-модели DocumentBundle/Page/Span, FormalEngine, RuleRegistry,
gate и reporting. Не добавляй другую PDF-библиотеку без необходимости.

Scope:
- `src/normocontrol/rules/context.py`;
- `src/normocontrol/rules/formatting.py`;
- `src/normocontrol/rules/engine.py`;
- `src/normocontrol/rules/gate.py`;
- `src/normocontrol/orchestrator.py`;
- reporting/schema, только если требуется новый счётчик;
- PDF integration/e2e tests и документация CLI/formal engine.

Функциональный контракт:
1. FMT-01, FMT-02, FMT-03 и FMT-05 должны уметь запускаться на PDF-only bundle без
   `LatexProject`.
2. FMT-04 может остаться `unverifiable`, если абзацный отступ нельзя доказать по PDF, но
   сообщение должно быть точным.
3. `severity=error,status=unverifiable` в formal-слое считается блокирующей неполной
   проверкой и возвращает exit 2. Не меняй коды 0/2/3/4 и не выдавай такой результат за pass.
4. В отчёте отдельно посчитай блокирующие unverifiable, не смешивая их с подтверждёнными
   нарушениями.
5. LLM/vision `unverifiable` по-прежнему никогда не блокирует merge.
6. PDF без text layer, повреждённый PDF и зашифрованный PDF не должны давать PASS.
7. Профили software/research/organizational должны сохранить существующую семантику.

Обязательные тесты:
- новый `tests/integration/test_pdf_only_gate.py`;
- `fmt_pass.pdf` выполняет доступные FMT-проверки и не получает `required source unavailable:
  latex_project`;
- `fmt_wrong_font.pdf` блокируется правилом FMT-01;
- `fmt_non_bold_heading.pdf` блокируется FMT-02;
- `fmt_margin_overflow.pdf` блокируется FMT-05;
- PDF без text layer получает блокирующий incomplete/unverifiable результат;
- LLM-unverifiable не меняет exit code formal gate;
- последовательный и parallel formal run дают одинаковый отчёт;
- e2e CLI проверяет реальные коды выхода subprocess.

Corner cases:
- пустые spans;
- повёрнутая страница;
- двухколоночный текст;
- страница без body spans;
- нестандартное имя шрифта TimesNewRomanPSMT;
- PDF-путь вне project root не должен сериализоваться в отчёт;
- никакой текст ВКР не должен попадать в исключения и логи.

Ожидаемый результат:
- PDF-only больше не возвращает PASS со 100% formal-unverifiable;
- существующие LaTeX fixtures не регрессируют;
- отчёт проходит `schemas/report.schema.json`;
- полный pytest, Ruff и mypy зелёные.
```

### Ветка, проверка и выгрузка

```bash
git switch main
git pull --ff-only
git switch -c fix/pdf-only-formal-gate

python -m pytest -q tests/integration/test_pdf_only_gate.py
python -m pytest -q tests/integration/test_pdf_formatting_rules.py
python -m pytest -q tests/e2e/test_run_cli.py
python -m pytest -q
python -m ruff format --check .
python -m ruff check .
python -m mypy src

git status --short
git diff --check
git --no-pager diff --name-status

git add -- \
  src/normocontrol/rules/context.py \
  src/normocontrol/rules/formatting.py \
  src/normocontrol/rules/engine.py \
  src/normocontrol/rules/gate.py \
  src/normocontrol/orchestrator.py \
  src/normocontrol/reporting \
  schemas/report.schema.json \
  tests/integration/test_pdf_only_gate.py \
  tests/integration/test_pdf_formatting_rules.py \
  tests/e2e/test_run_cli.py \
  docs/formal-engine.md \
  docs/cli.md

git --no-pager diff --cached --name-status
git --no-pager diff --cached --check
git commit -m "fix(formal): enforce PDF-only verification gate"
git push -u origin HEAD

gh pr create \
  --base main \
  --head fix/pdf-only-formal-gate \
  --title "fix(formal): enforce PDF-only verification gate" \
  --body "Runs supported formal checks for PDF-only input and blocks incomplete error-level verification."

gh pr checks --watch
```

Ожидаемый результат: все required checks зелёные; PDF fail-fixtures возвращают exit 2, а
synthetic pass не содержит ложного `required source unavailable: latex_project` для FMT.

---

## Промпт 3. Безопасное обнаружение bibliography и PDF после LaTeX-сборки

### Текст промпта

```text
Исправь end-to-end передачу LaTeX-артефактов в formal engine.

Используй pathlib, существующие LatexExtractor/PdfExtractor, bib parser, ExecutionContext и
защиту project_root. Не добавляй glob, который может выйти за пределы проекта.

Требуется:
1. Найди используемые `.bib` через LaTeX-команды библиографии и/или безопасный
   детерминированный поиск внутри project root.
2. Передай найденные пути в `ExecutionContext.bib_paths` вместо `bib_paths=()`.
3. Отклоняй `..`, absolute paths и symlink/junction, ведущие за project root.
4. Удали дубликаты с учётом нормализации пути и сохрани стабильный POSIX-порядок.
5. После успешного latexmk извлеки PDF spans/pages для FMT/FIG-метрик. Не теряй секции,
   полученные из LaTeX AST. Если нужно, введи отдельное поле `pdf_bundle` в контексте вместо
   неявного смешивания двух source_format.
6. Не сериализуй абсолютные пути и содержимое библиографии в диагностические исключения.
7. Кэш должен инвалидироваться при изменении `.bib` или compiled PDF.

Обязательные тесты:
- новый `tests/integration/test_orchestrator_artifact_discovery.py`;
- один `.bib`, несколько `.bib`, повторное подключение одного файла;
- отсутствующий bib-файл;
- traversal `../outside.bib`;
- directory symlink/junction наружу;
- Unicode/NFD filename;
- успешная сборка передаёт PDF metrics;
- изменение `.bib` меняет cache key;
- BIB-01..BIB-05 и REV-01..REV-04 реально запускаются через CLI/orchestrator;
- абсолютный путь отсутствует в `report.json`.

Corner cases:
- закомментированная bibliography-команда;
- `\addbibresource{refs.bib}` и `\bibliography{a,b}`;
- расширение `.bib` указано и не указано;
- Windows separator и POSIX separator;
- пустой `.bib`;
- повреждённый compiled PDF;
- latexmk success, но PDF отсутствует.

Ожидаемый результат:
- demo/fixture с refs.bib больше не пишет `required source unavailable: bib_files`;
- bibliography fixtures достигаются end-to-end, а не только прямым вызовом FormalEngine;
- PDF metrics доступны после успешной сборки;
- все security boundary tests зелёные.
```

### Ветка, проверка и выгрузка

```bash
git switch main
git pull --ff-only
git switch -c fix/artifact-discovery

python -m pytest -q tests/integration/test_orchestrator_artifact_discovery.py
python -m pytest -q tests/integration/test_bib_rules.py
python -m pytest -q tests/integration/test_orchestrator.py
python -m pytest -q tests/unit/extract
python -m pytest -q
python -m ruff format --check .
python -m ruff check .
python -m mypy src

git status --short
git diff --check
git --no-pager diff --name-status

git add -- \
  src/normocontrol/orchestrator.py \
  src/normocontrol/cache.py \
  src/normocontrol/extract \
  src/normocontrol/rules/context.py \
  tests/integration/test_orchestrator_artifact_discovery.py \
  tests/integration/test_bib_rules.py \
  tests/integration/test_orchestrator.py \
  tests/unit/extract \
  docs/data-flow.md \
  docs/formal-engine.md

git --no-pager diff --cached --name-status
git --no-pager diff --cached --check
git commit -m "fix(orchestrator): discover bibliography and compiled PDF"
git push -u origin HEAD

gh pr create \
  --base main \
  --head fix/artifact-discovery \
  --title "fix(orchestrator): discover bibliography and compiled PDF" \
  --body "Connects safe LaTeX artifacts to end-to-end formal checks."

gh pr checks --watch
```

Ожидаемый результат: PR URL, зелёные `lint-and-unit`/`formal-gate`, отсутствие персональных
или абсолютных путей в staged diff.

---

## Промпт 4. Настоящий LaTeX/chktex gate в GitHub Actions

### Текст промпта

```text
Сделай LaTeX build и chktex настоящей обязательной частью formal-gate.

Scope:
- `.github/workflows/normocontrol.yml`;
- `.github/actions/setup-normocontrol/action.yml` при необходимости;
- synthetic LaTeX fixtures;
- workflow contract tests;
- docs GitHub Actions/setup/troubleshooting.

Требуется:
1. На Ubuntu runner установи минимальный воспроизводимый набор:
   latexmk, chktex, XeLaTeX, biber, biblatex-gost, Cyrillic/TeX Gyre fonts и пакеты,
   необходимые synthetic fixture.
2. Не используй proprietary Times New Roman в CI. В synthetic `.cls` оставь проверяемое
   требование Times New Roman, но добавь безопасный compile fallback на TeX Gyre Termes через
   `\IfFontExistsTF`.
3. Удали `|| true` после latexmk.
4. Ошибка компиляции, missing reference или blocking chktex diagnostic должна делать
   `formal-gate` красным.
5. Logs загружай с `if: always()`, даже если gate упал.
6. `build-latex` может остаться диагностическим job, но обязательный `formal-gate` должен сам
   доказать успешную сборку и chktex.
7. Не делай semantic jobs required.

Обязательные тесты:
- workflow test запрещает `latexmk ... || true`;
- workflow test подтверждает установку latexmk/chktex/xelatex/biber;
- fixture `compile-pass` компилируется;
- новый fixture `compile-fail` даёт nonzero;
- новый fixture с blocking chktex нарушением даёт nonzero;
- artifacts используют `if: always()`;
- required job names остаются строго `lint-and-unit` и `formal-gate`.

Corner cases:
- runner без Times New Roman;
- warning latexmk при успешном PDF;
- отсутствующий `.sty`;
- unresolved reference после необходимого числа проходов;
- путь с пробелами;
- Cyrillic source;
- ошибка biber.

Ожидаемый результат:
- успешный fixture создаёт ненулевой PDF;
- compile-fail действительно делает formal-gate красным;
- workflow больше не маркирует отсутствующий latexmk как успешную проверку.
```

### Ветка, проверка и выгрузка

```bash
git switch main
git pull --ff-only
git switch -c fix/latex-hard-gate

python -m pytest -q tests/unit/test_workflow_normocontrol.py
python -m pytest -q tests/unit/test_docs_contract.py
python -m pytest -q
python -m ruff format --check .
python -m ruff check .
python -m mypy src

git status --short
git diff --check
git --no-pager diff --name-status

git add -- \
  .github/workflows/normocontrol.yml \
  .github/actions/setup-normocontrol/action.yml \
  tests/fixtures \
  tests/unit/test_workflow_normocontrol.py \
  tests/unit/test_docs_contract.py \
  docs/github-actions.md \
  docs/setup-linux.md \
  docs/troubleshooting.md

git --no-pager diff --cached --name-status
git --no-pager diff --cached --check
git commit -m "fix(ci): enforce LaTeX and chktex gate"
git push -u origin HEAD

gh pr create \
  --base main \
  --head fix/latex-hard-gate \
  --title "fix(ci): enforce LaTeX and chktex gate" \
  --body "Makes compilation and source linting mandatory while preserving diagnostic artifacts."

gh pr checks --watch
```

Ожидаемый результат: GitHub выполняет реальную установку TeX; `formal-gate` зелёный только
после создания PDF и успешного chktex.

---

## Промпт 5. Надёжный Ollama endpoint и управляемый GPU-профиль

### Текст промпта

```text
Исправь локальный Ollama provider GostCheck для Windows и ограниченной VRAM.

Используй существующие `httpx`, `openai`, Pydantic settings, retry policy и Qwen3
`qwen3:8b-q4_K_M`. Не ослабляй JSON Schema и не разрешай semantic-результатам блокировать
merge.

Требуется:
1. Замени default URL на `http://127.0.0.1:11434/v1` во всех единых источниках конфигурации,
   `.env.example` и документации.
2. Исключи расхождение benchmark (`127.0.0.1`) и production provider (`localhost`).
3. Для Ollama передавай явное отключение thinking совместимым способом (`think: false`);
   сохрани `temperature=0`, non-streaming и strict JSON Schema.
4. Добавь валидируемые настройки контекста/лимита ответа. Выбери безопасный default для
   12 GB VRAM на основании live-smoke; большие значения должны быть явным opt-in.
5. `llm doctor` должен отличать: daemon недоступен, model отсутствует, schema capability
   недоступна.
6. Ошибка модели остаётся `unverifiable`, ключи и текст не попадают в лог.
7. Не выполняй live Ollama-тест в обычном CI; marker `live` и `RUN_LLM_LIVE=1` сохраняются.

Обязательные unit-тесты:
- default URL равен IPv4 loopback;
- CLI override имеет приоритет;
- сформированное тело Ollama содержит `think=false`, schema и лимиты;
- unknown env value отклоняется;
- model missing и endpoint unavailable различаются;
- timeout/HTTP 429/5xx повторяются по политике, 4xx auth не повторяется;
- `--no-llm` имеет абсолютный приоритет;
- секрет редактируется в exception/repr/log.

Обязательный live-smoke:
- synthetic fixture;
- Qwen3 8B Q4;
- GPU placement подтверждён через `ollama ps`;
- response проходит Pydantic schema;
- задокументированы latency, tokens/s, VRAM и model digest;
- после теста выполняется `ollama stop qwen3:8b-q4_K_M`.

Corner cases:
- Windows IPv6 localhost;
- HTTP proxy в окружении;
- daemon запущен, модель отсутствует;
- 100% CPU fallback;
- недостаточно VRAM;
- ответ обрезан token limit;
- модель вернула Markdown fence;
- модель вернула reasoning отдельно от content.

Ожидаемый результат:
- `normocontrol llm doctor --provider ollama` показывает `status=OK` без ручного
  LLM_BASE_URL;
- synthetic live-smoke укладывается в документированный timeout;
- strict schema остаётся обязательной.
```

### Ветка, проверка и выгрузка

```bash
git switch main
git pull --ff-only
git switch -c fix/ollama-ipv4-profile

python -m pytest -q tests/unit/llm
python -m pytest -q tests/integration/test_llm_contract.py
python -m pytest -q tests/unit/test_benchmark.py
python -m pytest -q
python -m ruff format --check .
python -m ruff check .
python -m mypy src

# Live запуск — только если Ollama и модель уже установлены:
RUN_LLM_LIVE=1 python -m pytest -q -m live tests/live/test_ollama_qwen3.py
ollama ps
ollama stop qwen3:8b-q4_K_M

git status --short
git diff --check
git --no-pager diff --name-status

git add -- \
  .env.example \
  normocontrol.yaml.example \
  src/normocontrol/llm \
  scripts/benchmark_llm.py \
  scripts/smoke_ollama.ps1 \
  tests/unit/llm \
  tests/integration/test_llm_contract.py \
  tests/unit/test_benchmark.py \
  tests/live/test_ollama_qwen3.py \
  docs/llm-providers.md \
  docs/gpu-runbook.md \
  docs/troubleshooting.md

git --no-pager diff --cached --name-status
git --no-pager diff --cached --check
git commit -m "fix(llm): stabilize local Ollama profile"
git push -u origin HEAD

gh pr create \
  --base main \
  --head fix/ollama-ipv4-profile \
  --title "fix(llm): stabilize local Ollama profile" \
  --body "Uses IPv4 loopback, explicit non-thinking structured output, and a tested 12 GB VRAM profile."

gh pr checks --watch
```

Ожидаемый результат: локальный doctor — `OK`, unit/integration tests зелёные, live-smoke
возвращает валидный advisory JSON; модель после теста выгружена из VRAM.

---

## Промпт 6. Достоверность отчёта: время, degraded и blocking-unverifiable

### Текст промпта

```text
Исправь достоверность публикуемого отчёта GostCheck.

Scope:
- orchestrator;
- reporting aggregate/json/markdown;
- report schema и snapshots;
- tests reporting/orchestrator/e2e;
- документация кодов выхода.

Требуется:
1. Удали production hardcode даты `2026-07-24T00:00:00Z`.
2. По умолчанию используй фактический `datetime.now(UTC)` с секундами и суффиксом Z.
3. Сохрани dependency injection Clock для детерминированных unit tests.
4. `degraded=true`, если обязательная formal-проверка не выполнена из-за отсутствующего
   source/tool, даже если build stage формально завершился.
5. Добавь явный счётчик `blocking_unverifiable` в JSON Schema, summary и Markdown.
6. Не считай LLM/vision unverifiable блокирующим.
7. Не публикуй абсолютные пути, полный текст документа, API key или traceback provider.
8. Кэшированный отчёт нового запуска должен получать корректную метаинформацию запуска, а не
   старый timestamp.

Обязательные тесты:
- реальное default clock находится между временем до/после вызова;
- injected fixed clock даёт стабильный snapshot;
- PDF-only error/unverifiable -> degraded true и blocking count >0;
- disabled LLM -> degraded не меняется только из-за LLM;
- report schema отклоняет неизвестные поля;
- timestamp содержит UTC `Z`;
- redaction скрывает Windows path, Unix home, ключи и длинные цитаты;
- cached stages не подменяют timestamp текущего aggregate.

Corner cases:
- системные часы пошли назад;
- naive datetime в test hook;
- пустой список findings;
- только warnings;
- одновременно formal fail и blocking-unverifiable;
- отменённый run;
- повреждённый cache.

Ожидаемый результат:
- новый локальный отчёт содержит фактическое время;
- неполная formal-проверка видна в header/counts/Markdown;
- snapshots обновлены только осознанно и проходят schema validation.
```

### Ветка, проверка и выгрузка

```bash
git switch main
git pull --ff-only
git switch -c fix/report-integrity

python -m pytest -q tests/unit/reporting/test_reporting.py
python -m pytest -q tests/integration/test_orchestrator.py
python -m pytest -q tests/e2e/test_run_cli.py
python -m pytest -q
python -m ruff format --check .
python -m ruff check .
python -m mypy src

git status --short
git diff --check
git --no-pager diff --name-status

git add -- \
  src/normocontrol/orchestrator.py \
  src/normocontrol/reporting \
  schemas/report.schema.json \
  templates/report.md.j2 \
  tests/unit/reporting/test_reporting.py \
  tests/integration/test_orchestrator.py \
  tests/e2e/test_run_cli.py \
  tests/snapshots \
  docs/cli.md \
  docs/formal-engine.md

git --no-pager diff --cached --name-status
git --no-pager diff --cached --check
git commit -m "fix(report): publish truthful run metadata"
git push -u origin HEAD

gh pr create \
  --base main \
  --head fix/report-integrity \
  --title "fix(report): publish truthful run metadata" \
  --body "Uses real UTC timestamps and exposes incomplete formal verification."

gh pr checks --watch
```

Ожидаемый результат: `generated_at` соответствует текущему запуску, incomplete formal
проверки видны и блокируются, required GitHub checks зелёные.

---

## Промпт 7. Полезные semantic-результаты на синтетическом regression corpus

### Текст промпта

```text
Повышай надёжность шести уже реализованных semantic-правил GostCheck, не реализуя остальные
19 правил в этом PR.

Работай только на обезличенных synthetic fixtures. Не коммить реальные ВКР и не отправляй их
в Yandex.

Scope:
- semantic prompts/rule specs/batching/evidence;
- шесть implemented rule IDs;
- synthetic semantic fixtures;
- mock unit tests и opt-in Ollama live tests;
- evaluation metrics/docs.

Требуется:
1. Создай synthetic corpus с полноценными аннотацией, введением, постановкой задачи,
   анализом результатов и заключением.
2. Для каждого из шести правил создай минимум positive, warning и insufficient fixture.
3. Уточни prompt так, чтобы модель цитировала точную непрерывную подстроку разрешённого chunk,
   не пересказывала её и не придумывала locator.
4. Сохрани строгий Pydantic schema, две попытки и evidence verifier. Запрещено ослаблять
   проверку цитат ради pass.
5. Разделяй invalid schema, invalid evidence, provider timeout и section missing.
6. Введи воспроизводимый evaluation script с метриками schema-valid rate, evidence-valid
   rate и useful advisory rate по правилу.
7. Все 19 отложенных правил должны по-прежнему явно возвращать NOT_IMPLEMENTED.

Обязательные unit-тесты:
- valid exact quote;
- paraphrased quote отклоняется;
- quote из другого chunk отклоняется;
- ответ с лишним полем отклоняется;
- неверный rule_id отклоняется;
- отсутствующий обязательный element отклоняется;
- repair attempt исправляет первый invalid JSON;
- второй invalid ответ -> unverifiable;
- порядок findings/chunks детерминирован;
- token budget и overlap не нарушаются;
- отключённый provider не делает сетевых вызовов.

Opt-in live tests:
- каждый implemented rule запускается на synthetic corpus через Ollama;
- ни один ответ не получает `fail`;
- schema-valid и evidence-valid показатели сохраняются в `benchmark-results/`, но этот
  каталог не коммитится;
- тест имеет разумный timeout и после завершения выгружает модель.

Corner cases:
- цитата с Unicode normalization;
- одинаковая цитата встречается дважды;
- длинный абзац на границе chunk;
- пустая секция;
- модель вернула Markdown fence;
- отказ модели;
- ответ обрезан;
- provider недоступен;
- context budget меньше одного предложения.

Ожидаемый результат:
- mock suite полностью детерминирован;
- synthetic live corpus даёт измеримые полезные advisory outcomes;
- evidence verifier остаётся строгим;
- реальные документы не появляются в git.
```

### Ветка, проверка и выгрузка

```bash
git switch main
git pull --ff-only
git switch -c fix/semantic-regression-corpus

python -m pytest -q tests/unit/semantic
python -m pytest -q tests/integration/test_llm_contract.py
python -m pytest -q
python -m ruff format --check .
python -m ruff check .
python -m mypy src

# Необязательный локальный live-run:
RUN_LLM_LIVE=1 python -m pytest -q -m live tests/live
ollama stop qwen3:8b-q4_K_M

git status --short
git diff --check
git --no-pager diff --name-status

git add -- \
  prompts \
  src/normocontrol/semantic \
  src/normocontrol/evaluation \
  tests/fixtures/semantic \
  tests/unit/semantic \
  tests/integration/test_llm_contract.py \
  tests/live \
  scripts \
  docs/llm-providers.md \
  docs/acceptance.md

git --no-pager diff --cached --name-status
git --no-pager diff --cached --check
git commit -m "test(semantic): add verified advisory regression corpus"
git push -u origin HEAD

gh pr create \
  --base main \
  --head fix/semantic-regression-corpus \
  --title "test(semantic): add verified advisory regression corpus" \
  --body "Adds synthetic quality evaluation for the six implemented semantic rules."

gh pr checks --watch
```

Ожидаемый результат: все обычные тесты зелёные; live-тесты дают структурированные метрики;
в staged-файлах нет PDF/DOCX, API keys, `.env`, `build/` или `benchmark-results/`.

---

## Финальная проверка после слияния всех исправлений

Эти команды выполняются только после слияния всех PR:

```bash
git switch main
git pull --ff-only
git status --short --branch

python -m pip check
python -m ruff format --check .
python -m ruff check .
python -m mypy src
python -m pytest -q
python scripts/release_check.py --out build/final-release-check.json

normocontrol doctor
normocontrol run tests/fixtures/demo/pass \
  --provider disabled \
  --out build/final-pass
echo "pass exit=$?"

normocontrol run tests/fixtures/demo/fail \
  --provider disabled \
  --out build/final-fail
echo "fail exit=$?"

powershell -ExecutionPolicy Bypass \
  -File demo/run_demo.ps1 \
  -Mode dry-run \
  -Out build/final-demo

gh run list --branch main --limit 10
git status --short --branch
```

Ожидаемый результат:

```text
main синхронизирован с origin/main
pip check: No broken requirements found
ruff format/check: passed
mypy: Success
pytest: все тесты passed, live deselected
release_check: "ok": true
pass fixture: exit 0
fail fixture: exit 2
demo: pass/fail/fixed OK
git status: нет изменённых или untracked-файлов
```

До этого результата не создавайте и не отправляйте tag `v0.1.0`.

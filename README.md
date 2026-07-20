# GostCheck

Публичный движок автоматизированного нормоконтроля ВКР через GitHub CI/CD.

Проект проверяет LaTeX/PDF и библиографию детерминированными правилами, а LLM
использует только для консультативных семантических замечаний. Окончательное
решение принимает нормоконтролёр.

## Важно о данных

В репозитории разрешены только код, методическая рубрика, документация и
синтетические тестовые данные. Реальные ВКР, отчёты с цитатами, ФИО студентов,
ключи API и другие персональные данные коммитить нельзя. Для этого в
`.gitignore` предусмотрены отдельные запреты.

## Быстрый старт

Требуется Python 3.12.

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e '.[dev]'
python -m pytest -q
normocontrol --version
normocontrol doctor
```

Для воспроизводимой установки CI и чистого окружения используйте lock-файл:

```powershell
python -m pip install -r requirements.lock
python -m pip install --no-deps -e .
```

На Linux команды те же, кроме активации окружения (`source .venv/bin/activate`).
Пути внутри приложения обрабатываются через `pathlib`; JSON-файлы всегда
записываются в UTF-8, включая пути с пробелами и Unicode/NFD-именами.

Без локальной или облачной модели используйте `LLM_PROVIDER=disabled`. Для
локального запуска через Ollama скопируйте `.env.example` в `.env` и установите
`LLM_PROVIDER=ollama`. Файл `.env` не отслеживается Git.

`normocontrol doctor` выполняет только локальные проверки Python 3.12, Git,
`latexmk`, `chktex`, Ollama и конфигурации LLM. Команда не обращается к сети и
всегда завершается кодом 0: отсутствующие внешние инструменты показываются как
диагностика, а не как сбой.

## Исполняемые контракты

Публичные Pydantic v2-модели находятся в `normocontrol.domain`:
`RuleDefinition`, `Evidence`, `Finding`, `StageResult` и `RunReport`. Все модели
запрещают неизвестные поля. Идентификатор правила и locator evidence не могут
быть пустыми, а длительность этапа не может быть отрицательной. JSON-контракт
`RunReport` не добавляет текущий timestamp, поэтому одинаковый результат имеет
стабильную сериализацию.

Статусы результата: `pass`, `fail`, `warn`, `info`, `not_applicable`,
`unverifiable`, `skipped`. Слои `llm` и `vision` не могут создать `fail`; этот
инвариант проверяет сама доменная модель. Формальные слои `class`, `script` и
`class+script` могут вернуть `fail` и код процесса 2.

Коды выхода:

- `0` — успешное выполнение, включая `--help`, `--version` и `doctor`;
- `1` — ошибка выполнения;
- `2` — найдены блокирующие нарушения формальных правил.

Обычные логи направляются в stderr. Фильтр удаляет API-ключи, токены и случайно
переданный текст ВКР, а также ограничивает длину сообщения. JSON-отчёт пишется
отдельно в stdout либо в UTF-8 файл, поэтому его можно безопасно передать
следующему шагу CI.

## Проверки разработки

### Проверка рубрики и профили

`work_profile` задаётся пользователем явно и принимает одно из значений `software`,
`research` или `organizational`. Значения `auto` нет: рекомендация LLM может быть только
предупреждением и не меняет профиль или gate. Параметры draft-рубрики разворачиваются только
после перечисления в `approved_params`; для остальных выводится `APPROVAL_REQUIRED`.

```powershell
normocontrol rubric validate --rubric rubric.yaml --config normocontrol.yaml.example
```

Команда возвращает `0` для валидной рубрики и `3` для ошибки формата/конфигурации. Диагностика
содержит файл и YAML path. Конфигурации могут наследовать локальные YAML-файлы через `include`
(строка или список путей относительно включающего файла); циклические include запрещены.

```powershell
python -m ruff format --check .
python -m ruff check .
python -m mypy src
python -m pytest -q --cov=normocontrol --cov-fail-under=85
```

Покрытие измеряется только для production-пакета `normocontrol`, минимальный
порог — 85%. Тесты с внешними сервисами обязаны иметь marker `live`; по
умолчанию они исключены. Unit-тесты не выполняют сетевых запросов.

## Работа через ветки

```powershell
git switch main
git pull --ff-only
git switch -c feat/<короткое-имя-задачи>
# изменения и тесты
git add -p
git commit -m "feat(scope): краткое описание"
git push -u origin HEAD
gh pr create --fill
```

Не отправляйте изменения напрямую в `main`: каждая задача проходит pull request
и review другого участника.

## Ответственность

- Тимур: каркас, rubric, extract, LLM, semantic, GPU benchmark.
- Доминик: formal rules, PDF, bibliography, fixtures и метрики.
- Араик: orchestrator, reporting, GitHub workflows, demo и документация.

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
python -m pip install -r requirements.lock
python -m pip install --no-deps -e .
python -m pytest -q
normocontrol --version
normocontrol doctor
```

Без локальной или облачной модели используйте `LLM_PROVIDER=disabled`. Для
локального запуска через Ollama скопируйте `.env.example` в `.env` и установите
`LLM_PROVIDER=ollama`. Файл `.env` не отслеживается Git.

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

Полный порядок задач и промпты находятся в проектном плане, который хранится
отдельно от репозитория.


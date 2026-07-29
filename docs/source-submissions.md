# Контракт входных документов

GostCheck проверяет только фактически предоставленные артефакты. Он не создаёт
фиктивные `main.tex`, bibliography, images, class/style-файлы или citation entries,
не устанавливает TeX Live и не загружает зависимости из сети.

## PDF-only

Передайте существующий readable `.pdf`:

```bash
normocontrol run thesis.pdf --no-llm --out build/pdf-check
```

Файл должен открываться и читаться локально. Повреждённый, зашифрованный или
нечитаемый PDF является невалидным входом и даёт exit `3`. PDF без text layer
может быть извлечён в degraded mode; недоказуемые обязательные formal-проверки
остаются `UNVERIFIABLE`, а не превращаются в `PASS`.

## LaTeX source bundle

Каталог submission должен содержать верхнеуровневый `main.tex`. Если его нет,
GostCheck рекурсивно принимает единственный `main.tex`. Верхнеуровневый файл имеет
приоритет над примерами во вложенных каталогах. Если root называется иначе,
передайте privacy-safe относительный путь явно:

```bash
normocontrol run thesis-project --root src/thesis.tex --no-llm
normocontrol doctor thesis-project --root src/thesis.tex
```

Абсолютный `--root`, `..` traversal и symlink/junction за пределы submission root
запрещены. При нескольких вложенных кандидатах GostCheck не выбирает случайный:
exit `3` перечисляет кандидатов в стабильном порядке как относительные пути.

Полный source bundle включает:

- используемые локальные class/style (`.cls`/`.sty`) и их конфигурацию;
- объявленную bibliography (`.bib`) со всеми реальными citation entries;
- все активные images, на которые ссылается `\includegraphics`;
- все активные includes (`\input`/`\include`) и вложенные source-файлы.

Закомментированные commands и команды внутри literal/verbatim-блоков не являются
активными зависимостями. `normocontrol doctor PATH` выполняет статический аудит и
выдаёт раздельные `missing include`, `missing class`, `missing style`,
`missing bibliography` и `missing image` diagnostics. Содержимое документов и
лишние абсолютные пользовательские пути в diagnostics не печатаются.

## Инструменты и degraded status

Source discovery, безопасное раскрытие includes и независимые статические проверки
выполняются без `latexmk` и `chktex`. Отсутствие инструмента затрагивает только
зависимую проверку: результат получает документированный `UNVERIFIABLE`/degraded
status и не маскируется как `PASS`. GostCheck не устанавливает инструменты сам.
Проверяйте фактическую локальную доступность через `normocontrol doctor`.

## Коды выхода

- exit `2`: вход достаточен для запуска, но formal gate нашёл блокирующее нарушение
  (`error+fail` либо блокирующий `error+unverifiable`);
- exit `3`: вход или конфигурация неполны/невалидны — например, отсутствует root,
  root неоднозначен, PDF нечитаем или путь выходит за границы submission.

Semantic/vision остаются advisory и никогда не создают blocking fail или exit `2`.

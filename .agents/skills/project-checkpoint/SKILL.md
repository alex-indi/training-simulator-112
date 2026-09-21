---
name: project-checkpoint
description: Сохраняет состояние текущей задачи UT112 перед паузой, сменой устройства, завершением Codex-сессии или риском потери контекста. Обновляет task handoff и при явном запросе на сохранение работы помогает создать безопасный checkpoint commit/push.
---

# Project Checkpoint

Цель: после переключения устройства новая сессия должна продолжить работу без старого чата.

## 1. Определи задачу

Получить:

```bash
git branch --show-current
git status --short --branch
```

Из ветки определить `UT112-xxx` и соответствующий `tasks/UT112-xxx.md`.

Если файла нет — создать его из `tasks/TEMPLATE.md` и заполнить фактическим состоянием.

Никогда не создавать checkpoint напрямую на `main`.

## 2. Сверь реальность

Посмотреть:

```bash
git diff --stat
git diff
git diff --cached
git log -5 --oneline --decorate
```

Не описывай как выполненное то, чего нет в коде/diff/commit history.

## 3. Выполни разумные проверки

Если проверки короткие и известны из задачи/репозитория — запусти их.

Если они дорогие, отсутствуют или окружение не готово — не блокируй checkpoint, а запиши `not run` и причину.

## 4. Обнови task handoff

Обязательно актуализировать:

- `Status`;
- `Last updated`;
- `Done`;
- `In progress`;
- `Changed files`;
- `Checks`;
- `Blockers`;
- `Exact next step` — ровно один ближайший конкретный шаг;
- `Last commit` / `Pushed` / `Working tree`.

## 5. Долговременные решения

Если в текущем чате принято решение, которое важно после завершения задачи:

- предметный факт → `docs/domain.md`;
- продуктовый/рабочий выбор → `docs/decision-log.md`;
- крупная архитектура → ADR + `docs/architecture.md`;
- вопрос заказчику → `docs/questions/customer-questions.md`.

Не переносить в docs сырые рассуждения или длинный чат.

## 6. Commit

Если пользователь явно вызвал checkpoint для сохранения/смены устройства и есть полезные изменения:

1. не использовать `git add .`;
2. stage только файлы текущей задачи и обновлённый handoff;
3. не добавлять `.env`, токены, customer materials или случайные файлы;
4. создать логичный commit либо, если работа промежуточная, допустимый checkpoint commit:

```text
chore(UT112-xxx): сохранить промежуточное состояние
```

Если изменения уже логически завершены, использовать правильный тип `feat/fix/test/docs/...`.

## 7. Push

Если цель checkpoint — переключение устройства:

- push только текущую feature-ветку;
- если upstream отсутствует, использовать `git push -u origin <branch>`;
- никогда не force-push;
- никогда не push напрямую в `main`.

Если push невозможен из-за сети/прав — явно сообщить, что remote ещё не содержит checkpoint.

## 8. Финальная сводка

Сообщить:

- Task ID;
- commit hash;
- push status;
- checks;
- exact next step для `$project-resume`.

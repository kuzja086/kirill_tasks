# Навык для Алисы (Yandex Cloud Functions + PostgreSQL)

Навык для умных колонок с Алисой и приложения Яндекс. Навык реализован на Python,
публикуется как функция Яндекс Облака (Cloud Functions), данные хранит в Postgres.

Текущая бизнес-логика — заготовка: навык запоминает имя пользователя и напоминает его.
Тексты и сценарии меняются в `alice_skill/dialogue.py`.

## Структура проекта

```
handler.py              точка входа Cloud Functions: handler.handler
alice_skill/
  config.py             настройки из переменных окружения (Postgres, таймауты)
  models.py             разбор запроса Алисы и сборка ответа (протокол v1.0)
  db.py                 доступ к Postgres через psycopg2 + протокол UserRepository
  dialogue.py           маршрутизация интентов и тексты реплик
sql/001_init.sql        схема БД (применяется вручную, из функции не вызывается)
tests/                  pytest, внешний Postgres не требуется
deploy.ps1              сборка zip и создание версии функции через yc CLI
.env.example            шаблон переменных окружения функции
```

## Требования

- Python 3.11+ (в облаке используется runtime `python312`).
- Postgres, развёрнутый локально и доступный из интернета (см. «Безопасность»).
- `yc` CLI и авторизованный профиль — только для деплоя.

## Локальная разработка

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements-dev.txt
pytest
```

Тесты не подключаются к базе: слой БД проверяется на фейковом соединении,
сценарии — на in-memory реализации `UserRepository` (`tests/conftest.py`).

Применить схему к базе:

```powershell
psql -h <хост> -p 5432 -U alice_skill -d alice_skill -f sql/001_init.sql
```

Проверить обработчик локально (нужны переменные окружения Postgres):

```powershell
$env:PG_HOST='...'; $env:PG_DATABASE='alice_skill'
$env:PG_USER='...'; $env:PG_PASSWORD='...'; $env:PG_SSLMODE='require'
python -c "import json, handler; print(json.dumps(handler.handler({'session': {'new': True, 'user': {'user_id': 'test'}}, 'request': {'command': ''}, 'version': '1.0'}, None), ensure_ascii=False, indent=2))"
```

## Переменные окружения

| Переменная | Обязательна | По умолчанию | Назначение |
|---|---|---|---|
| `PG_HOST` | да | — | Хост или IP локального Postgres, опубликованный в интернет |
| `PG_PORT` | нет | `5432` | Порт Postgres |
| `PG_DATABASE` | да | — | Имя базы |
| `PG_USER` | да | — | Пользователь базы |
| `PG_PASSWORD` | да | — | Пароль пользователя |
| `PG_SSLMODE` | нет | `prefer` | Режим TLS; для внешнего доступа используйте `require` |
| `PG_CONNECT_TIMEOUT` | нет | `5` | Таймаут соединения, секунды (меньше таймаута функции) |

Значения задаются в переменных окружения версии функции; локально — в `.env`,
который не коммитится.

## Деплой

```powershell
# 1. Создать функцию (один раз)
yc serverless function create --name alice-skill

# 2. Собрать архив и создать версию функции
./deploy.ps1 -FunctionId <id-функции>

# 3. Разрешить вызов без IAM-токена (Алиса обращается к HTTPS-эндпоинту анонимно)
yc serverless function allow-unauthenticated-invoke alice-skill
```

URL функции вида `https://functions.yandexcloud.net/<id>` указывается в консоли
Яндекс.Диалогов в поле «Webhook URL». Проверить только сборку архива:
`./deploy.ps1 -FunctionId any -BuildOnly`.

`deploy.ps1` сохранён в UTF-8 с BOM: Windows PowerShell 5.1 иначе читает кириллицу
как ANSI и завершается ошибкой разбора (правило зафиксировано в `.editorconfig`).


## Как добавить сценарий

1. Завести константу интента в `alice_skill/dialogue.py` (например `INTENT_HELP`).
2. Добавить ветку в `respond()` и функцию-обработчик, возвращающую `AliceResponse`.
3. Натренировать интент с таким именем в консоли Яндекс.Диалогов —
   имя интента из `request.nlu.intents` должно совпадать с константой.
4. Покрыть сценарий тестом в `tests/test_dialogue.py`.

Слой данных расширяется методами протокола `UserRepository` (`alice_skill/db.py`)
и соответствующей реализацией в `PostgresRepository`; SQL-запросы всегда
параметризованы (`%s`), идентификатор пользователя — анонимный `session.user.user_id`.

## Безопасность

- Postgres открыт в интернет: включайте TLS (`PG_SSLMODE=require`), не используйте
  суперпользователя в `PG_USER`, ограничьте `listen_addresses`/`pg_hba.conf`
  и по возможности доступ по IP.
- Пароль хранится в переменных окружения версии функции; для продакшена
  предпочтителен Yandex Lockbox вместо открытых переменных.
- `.env`, ключи и архивы сборки в `.gitignore` — не коммитьте секреты.

## Ошибки и логи

Любое исключение в обработчике перехватывается: пользователь получает валидный
ответ протокола («Что-то пошло не так…»), а трейсбек попадает в логи функции
(`yc serverless function logs <name>`). Соединение с Postgres переиспользуется
между «тёплыми» вызовами и один раз переоткрывается при обрыве.

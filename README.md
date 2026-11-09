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
python -c "import json, handler; r = handler.handler({'session': {'new': True, 'user': {'user_id': 'test'}}, 'request': {'command': ''}, 'version': '1.0'}, None); print(json.dumps(json.loads(r['body']), ensure_ascii=False, indent=2))"
```

Проверить развёрнутую функцию по HTTPS:

```powershell
$body = '{"version":"1.0","session":{"new":true,"user":{"user_id":"smoke"}},"request":{"command":""}}'
Invoke-RestMethod -Uri 'https://functions.yandexcloud.net/<id-функции>' -Method Post `
    -ContentType 'application/json; charset=utf-8' `
    -Body ([Text.Encoding]::UTF8.GetBytes($body))
```

`curl.exe -d '{"...":"..."}'` в PowerShell искажает двойные кавычки и функция
получает невалидный JSON — используйте `Invoke-RestMethod` или
`curl.exe --data-binary '@файл.json'`.

### Формат события и ответа

При вызове по HTTPS рантайм передаёт HTTP-событие: JSON навыка лежит в
`event['body']` строкой (возможно, в base64 при `isBase64Encoded`), а ответ
функция обязана вернуть в формате интеграции — иначе платформа отдаст пустое
тело:

```json
{"statusCode": 200, "headers": {"Content-Type": "application/json; charset=utf-8"}, "body": "<JSON протокола Алисы>", "isBase64Encoded": false}
```

`handler.py` делает это сам (`_extract_request_payload` / `_http_response`) и
одинаково работает при прямом вызове через `yc serverless function invoke`,
где событием служит сам JSON Диалогов.

## Переменные окружения

| Переменная | Обязательна | По умолчанию | Назначение |
|---|---|---|---|
| `PG_HOST` | да | — | Хост или IP локального Postgres, опубликованный в интернет |
| `PG_PORT` | нет | `5432` | Порт Postgres |
| `PG_DATABASE` | да | — | Имя базы |
| `PG_USER` | да | — | Пользователь базы |
| `PG_PASSWORD` | да | — | Пароль пользователя; храните в Lockbox (см. ниже) |
| `PG_SSLMODE` | нет | `prefer` | Режим TLS; для внешнего доступа используйте `require` |
| `PG_CONNECT_TIMEOUT` | нет | `5` | Таймаут соединения, секунды (меньше таймаута функции) |

Значения задаются в переменных окружения версии функции; локально — в `.env`,
который не коммитится.

## Деплой

### Установка и авторизация `yc`

```powershell
# Официальный установщик: кладёт yc.exe в %USERPROFILE%\yandex-cloud\bin и добавляет каталог в PATH.
# После установки откройте новый терминал, чтобы обновился PATH.
iex (New-Object System.Net.WebClient).DownloadString("https://storage.yandexcloud.net/yandexcloud-yc/install.ps1")

# Авторизация: мастер откроет браузер и попросит OAuth-токен.
yc init
```

Вариант без мастера — по готовому OAuth-токену
(как получить: https://yandex.cloud/ru/docs/cli/operations/authentication/user):

```powershell
yc config profile create default
yc config set token <OAUTH-токен>
yc config set cloud-id <cloud-id>
yc config set folder-id <folder-id>
yc config list
```

### Создание функции и версии

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

### Секреты Yandex Lockbox

Пароль Postgres не должен лежать в `.env` и в открытых переменных версии.
В Lockbox он хранится зашифрованным, а Cloud Functions подставляет его в
переменную окружения при каждом вызове — код навыка при этом не меняется,
он по-прежнему читает `os.environ`.

```powershell
# 1. Сервисный аккаунт функции: именно ему нужны права на секрет.
yc iam service-account create --name alice-skill-sa

# 2. Секрет. Payload передаём через stdin: PowerShell 5.1 вырезает двойные
#    кавычки из аргументов, и JSON-строка в --payload ломается.
'[{"key":"PG_PASSWORD","text_value":"<пароль>"}]' | yc lockbox secret create --name alice-skill-pg --payload -

# 3. Разрешить сервисному аккаунту читать payload секрета.
yc lockbox secret add-access-binding --id <secret-id> `
    --role lockbox.payloadViewer --service-account-id <sa-id>

# 4. Деплой: PG_PASSWORD берётся из секрета, остальные переменные — из .env.
./deploy.ps1 -FunctionId <id-функции> `
    -SecretId <secret-id> -ServiceAccountId <sa-id> -SecretKeys PG_PASSWORD
```

Что делает скрипт: исключает перечисленные ключи из `--environment` (чтобы не
дублировать имя) и добавляет `--secret id=<secret-id>,key=PG_PASSWORD,environment-variable=PG_PASSWORD`.
Проверить результат:

```powershell
yc serverless function version get --id <version-id>
# environment: PG_HOST, PG_PORT, PG_DATABASE, PG_USER, PG_SSLMODE, PG_CONNECT_TIMEOUT
# secrets:     key: PG_PASSWORD -> environment_variable: PG_PASSWORD
```

Ротация пароля — это новая версия секрета, передеплой функции не требуется:
платформа подставляет текущую версию при каждом вызове.

```powershell
'[{"key":"PG_PASSWORD","text_value":"<новый пароль>"}]' | yc lockbox secret add-version --id <secret-id> --payload -
```

Ограничения текущей реализации `deploy.ps1`: поддерживается один секрет на
версию, имена ключей в секрете совпадают с именами переменных окружения.
Несколько секретов (например, отдельно пароль и логин) добавляются вызовом
`--secret` с разными `id` — для этого скрипт нужно расширить.

Важно: секрет, выданный через `--secret`, попадает в `os.environ` контейнера,
поэтому `DEBUG_ERRORS` и логи по-прежнему не должны печатать значения переменных.


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
- Пароль хранится в Yandex Lockbox и подставляется в переменные окружения версии
  через `--secret` (см. «Секреты Yandex Lockbox»); сервисному аккаунту функции
  выдавайте только роль `lockbox.payloadViewer` на конкретный секрет.
- `.env`, ключи и архивы сборки в `.gitignore` — не коммитьте секреты.

## Ошибки и логи

Любое исключение в обработчике перехватывается: пользователь получает валидный
ответ протокола («Что-то пошло не так…»), а трейсбек попадает в логи функции
(`yc serverless function logs <name>`). Соединение с Postgres переиспользуется
между «тёплыми» вызовами и один раз переоткрывается при обрыве.

Если логи недоступны, включите `DEBUG_ERRORS=1` в переменных окружения версии —
тогда в тексте ответа будет тип и сообщение исключения. После диагностики флаг
обязательно выключите: он раскрывает внутренние детали пользователю.

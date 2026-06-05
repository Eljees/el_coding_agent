# appsechub skill

Подключает эль-агента к **AppSecHub** (`/hub/rest`) и даёт читать/анализировать
issues приложения: количество, разбивка по сканерам и severity, типы
срабатываний TruffleHog, метрики качества. Только чтение — ничего в Hub не
меняет.

## Состав

| Файл | Слой | Назначение |
|---|---|---|
| `appsechub_client.py` | данные (A) | клиент к API + детерминированный CLI-раннер |
| `appsechub_mcp.py` | данные (A) | тонкий MCP-сервер поверх клиента (по образцу `el-sca-docker`) |
| `SKILL.md` | аналитика (D) | как вызывать, классификация trufflehog, метрики качества |

## Настройка (env)

```powershell
$env:HUB_API_TOKEN = "<ваш токен>"
$env:HUB_URL       = "https://appsechub.ssdlc.soc.rt.ru/hub/rest"  # по умолчанию уже такой
$env:HUB_VERIFY_TLS = "0"   # если внутренний сертификат не проходит проверку
```

Токен уходит как `Authorization: Bearer <token>`. Имена переменных совместимы с
проектом `eltriage` (`HUB_API_TOKEN` / `APPSECHUB_TOKEN` / `HUB_TOKEN`).

## Быстрый старт (CLI)

```powershell
python skills\appsechub\appsechub_client.py parse-url "https://appsechub.ssdlc.soc.rt.ru/#/appprofile/89/issues"
python skills\appsechub\appsechub_client.py summary 89
python skills\appsechub\appsechub_client.py issues 89 --source trufflehog --max 1000
python skills\appsechub\appsechub_client.py breakdown 89 --source trufflehog
python skills\appsechub\appsechub_client.py compare 89 --old-scan 1001 --new-scan 1042
```

## Подключение MCP-сервера

```powershell
pip install "mcp[cli]"
```

Конфиг MCP (stdio):

```json
{
  "mcpServers": {
    "appsechub": {
      "command": "python",
      "args": ["skills/appsechub/appsechub_mcp.py"],
      "env": {
        "HUB_API_TOKEN": "${HUB_API_TOKEN}",
        "HUB_URL": "https://appsechub.ssdlc.soc.rt.ru/hub/rest"
      }
    }
  }
}
```

Инструменты MCP: `parse_app_url`, `list_scanners`, `get_app_summary`,
`list_issues`, `breakdown_issues`, `compare_scans` (дельта issues между двумя
сканами: added / removed / unchanged + разбивка по severity).

## Пример сценария

Запрос: *«посмотри количество issues у проекта 89 и определи типы срабатываний
трюфельхога»* →
`parse_app_url` (→ 89) → `get_app_summary(89)` (счётчики по severity) →
`breakdown_issues(89, source="trufflehog")` → таблица детекторов TruffleHog +
метрики качества.

## Эндпоинты API (для справки)

- `GET /issue/v2?dto=<json>` — постраничный список issue (основной)
- `GET /issue/summary?application=<id>` — rollup по severity
- `GET /tool/scanner[?withIssue=true]` — список сканеров

Спека: `getiton/_el_triage/api-docs.json` (server `…/hub/rest`, 435 эндпоинтов).

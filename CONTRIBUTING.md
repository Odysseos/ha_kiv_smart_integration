# Разработка и проверка

Проект содержит две независимые реализации одного MQTT-контракта:

- `custom_components/vakio_kiv_local/` — нативный компонент HA;
- `manual/` — blueprint, пакет и примеры ручной установки;
- `docs/` — общая документация, протокол, установка компонента и YaHA;
- `tests/` — проверки обоих способов.

Название — Vakio KIV Local, домен — `vakio_kiv_local`, репозиторий —
`ha_vakio_kiv_local`.

## Окружение

Обычным пользователям зависимости Python не нужны. Для разработки используйте
отдельный venv Python 3.13; не устанавливайте тестовые зависимости в рабочий HA.
Проверенная версия HA — 2025.10.4, YaHA — 1.1.3. На Ubuntu 24.04 для косвенного
импорта camera нужна системная библиотека из пакета **libturbojpeg**.
PyTurboJPEG закреплён на 1.8.0 согласно manifest camera этой версии HA.

```bash
python3.13 -m venv .venv
.venv/bin/python -m pip install -r requirements-test.txt
git clone https://github.com/dext0r/yandex_smart_home.git .deps/yaha
git -C .deps/yaha checkout 7d1121923c91fdd190f3d13d75be8896aed18735
.venv/bin/python tests/validate_frontend.py
node tests/validate_frontend.mjs
.venv/bin/python tests/validate_project.py
.venv/bin/python tests/validate_ha.py
PYTHONPATH="$PWD/.deps/yaha" .venv/bin/python tests/validate_yaha.py
PYTHONPATH="$PWD/.deps/yaha" .venv/bin/python tests/validate_config.py
PYTHONPATH="$PWD/.deps/yaha" .venv/bin/python tests/validate_integration.py
```

GitHub Actions выполняет те же проверки с Python 3.13 и Node.js на Ubuntu 24.04.
Для проверки JS-модуля нужен Node.js 20 или новее, npm-зависимостей нет.
`requirements-test.txt` фиксирует прямые зависимости, но не является полным
lock-файлом транзитивных пакетов. Colorlog и ical установлены заранее,
чтобы check_config не доустанавливал их во время проверки.

## Область проверок

| Файл | Что проверяет |
| --- | --- |
| validate_ha.py | Ручной blueprint: шаблоны, input_text, Discovery, команды, Авто, физические отчёты, 12 месяцев, гонки событий, два прибора, собственные MQTT-эхо |
| validate_yaha.py | Ручной вариант: реальные классы YaHA, фильтр, программы, on/off, свойства и unavailable |
| validate_config.py | Штатный check_config HA для ручного пакета |
| validate_integration.py | Настоящий config flow и платформы HA, действия сущностей, MQTT loopback, память на диске, reload/unload/removal, два прибора, опции, reconnect, генерация YaHA по реестру и цепочка реальных классов YaHA → select → MQTT |
| validate_frontend.py | Регистрация extra module, отсутствие frontend в headless HA, ошибка регистрации, один URL и реальная отдача файла через HTTP-класс HA |
| validate_frontend.mjs | Перенос карточки, сохранение класса и кнопок, комнаты, скрытие, несколько экземпляров, переименование, отключение, отсутствие дубликатов, оба тега стратегий, ленивая загрузка и возврат исходного результата при ошибке расширения |
| validate_project.py | Метаданные, пути, ссылки документации и сохранность исходных YAML ручного варианта |

В поведенческих тестах MQTT-транспорт заменён callbacks; собственные исходящие
команды возвращаются через подписки для обнаружения петель. HTTP/network
настройка брокера исключена, поскольку клиент MQTT подменён. Тесты не
подключаются к физическому прибору или аккаунту Яндекса.

## Внесение изменений

У нативного компонента `state.py` описывает модель состояния, `controller.py`
управляет MQTT, блокировкой команд и Store, платформы HA используют один
контроллер экземпляра. Config entry определяется префиксом; постоянные
entity unique ID и ключ Store используют entry_id. Публичный сервис
get_yaha_config строит конфигурацию из реестра, а не из предположений об именах.

Проверяйте фактический прибор: ручное положение и Авто из HA, внешнего MQTT,
кнопок и УДЯ; перезапуски HA и прибора; два независимых экземпляра.
Указывайте модель, версию прошивки и хронологию топиков с payload.
Не называйте сохранённую цель подтверждённым механическим положением.

В ручном способе настройки всех экземпляров остаются в одном пакете.
Не добавляйте общую память на несколько приборов. Пример MQTT-префикса —
`vakio_kiv`, без комнат, сетевых адресов или паролей.

## Выпуск через HACS

Компонент находится в `custom_components/vakio_kiv_local/`; метаданные
для HACS — в корневом `hacs.json`. При выпуске повышайте `version` в
`manifest.json`. Workflow проверяет проект, но не публикует релизы.

## Экспериментальное расширение «Обзора»

`frontend.py` регистрирует статический JS через `async_register_static_paths`
и extra module API HA. Подключение не требует ресурса Lovelace.
`www/overview.js` оборачивает `generate` встроенных генераторов комнат,
общего «Климата» и главного «Обзора». В комнатах переносит существующие
tile-карточки; климатическому фильтру передаёт отдельную копию состояний
наших заслонок как обычных cover. Реальные состояния остаются `damper`.
После определения `home-assistant` подписки повторяются в текущем реестре
компонентов: HA устанавливает polyfill scoped registry при загрузке приложения.
Модуль не меняет исходный `hass.states`, MQTT или файлы HA. При headless HA
регистрация модуля пропускается. Параметр `overview_climate` по умолчанию true;
отдельный атрибут cover передаёт этот параметр модулю без дополнительной сущности.

Проверка с исходниками frontend использует версию
[`20260930.5`](https://github.com/home-assistant/frontend/tree/20260930.5/src/panels/lovelace/strategies),
которая поставляется с HA 2026.10.4.
Внутренние теги стратегий и структура карточек не являются публичным API.
Тесты JS используют конфигурации, соответствующие этим структурам, и
проверяют жизненный цикл регистрации стратегий. Они не запускают полный
интерфейс HA в браузере. При изменении frontend проверьте оба генератора,
размещение в комнатах и восстановление исходного поведения при отключении.

Дополнительно можно выполнить проверку с исходниками самого frontend
(Node.js 24+, встроенный `stripTypeScriptTypes`):

```bash
git clone --filter=blob:none https://github.com/home-assistant/frontend.git .deps/frontend
git -C .deps/frontend checkout 20260930.5
node tests/validate_frontend_upstream.mjs "$PWD/.deps/frontend"
```

В этой проверке выполняются настоящие `generate` генераторов комнат,
общего «Климата» и главного «Обзора», фильтры группировки и разрешение комнаты; классы Lit и проверки
поддержки элементов управления карточки заменены заглушками. Это проверка
структуры результата генерации, а не визуальный тест браузера.

Для проверки порядка загрузки в Firefox:

```bash
npm install --prefix .deps/browser --no-save playwright @webcomponents/scoped-custom-element-registry@0.0.10
node .deps/browser/node_modules/playwright/cli.js install firefox
node tests/validate_frontend_browser.mjs "$PWD/.deps/browser/node_modules"
```

Проверка выполняет модуль до и после установки scoped registry, проверяет
автоматическую установку обработчиков, ленивую загрузку общего «Климата»,
сохранение класса заслонки и действий карточки. Полный интерфейс HA при этом
не запускается.

## Локальная настройка прошивки

`www/vakio_settings.html` содержит страницу и встроенный Python-сервер.
`www/vakio_settings.py` запускает этот сервер. HA раздаёт файлы для скачивания
через `/vakio_kiv_local/settings.html`; сетевые запросы к прибору выполняются
с компьютера пользователя.

```bash
python3 tests/validate_device_settings.py
```

Проверка запускает сервер на loopback и подменяет только HTTP-соединение
с прибором. Она проверяет выбор IP, пути GET/POST, содержимое JSON,
отсутствие повторной записи при ошибках, ограничения запросов и выдачу страницы.

## Экспорт конфигурации YaHA

`vakio_kiv_local.export_yaha_config` — административное действие без параметров.
Оно собирает все записи интеграции и сохраняет полную конфигурацию YaHA с `filter` и `entity_config`
в `includes/yandex_smart_home_vakio.yaml`. Полный результат собирается
до записи; существующий файл заменяется атомарно. Файл без метки генератора
не перезаписывается. Одновременные вызовы сериализуются.
`get_yaha_config` остаётся действием без записи для одного устройства.

```bash
PYTHONPATH="$PWD/.deps/yaha" .venv/bin/python tests/validate_yaha_export.py
```

Проверяются три прибора, фактические ID, имена и комнаты из реестра,
добавление и удаление приборов, отключённая сущность, сохранность чужих файлов,
отказ записи, права вызова, объединение конфигурации через пакет HA и схема YaHA.

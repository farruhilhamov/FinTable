# FinTable — личный финансовый учёт (UZS)

Веб-приложение на Django для персонального/мультипользовательского трекера финансов:
счета, вклады, доли/ценные бумаги, доходы и расходы, автоматический расчёт P&L и
Net Worth, статистика и импорт/экспорт CSV. Валюта — узбекский сум (UZS).

## Возможности

- Регистрация / вход / выход (email как логин).
- **Счета** (`Account`): card/cash/other, расчётный баланс на основе транзакций.
- **Категории** (`Category`): доход/расход, системные дефолтные (12 расходов + 6 доходов)
  копируются каждому новому пользователю автоматически; создание/редактирование/архивация
  (физическое удаление запрещено — сохраняется история).
- **Транзакции** (`Transaction`): фильтры по датам/категории/счёту/типу, CRUD.
- **Вклады** (`Deposit`): простой процент и ежемесячная капитализация, расчёт
  накопленного дохода `get_accrued_income(as_of_date)` и текущего баланса на любую дату,
  закрытие вклада.
- **Ценные бумаги / Доли** (`Security`, `SecurityValuation`): история переоценок,
  текущая стоимость = последняя оценка, P&L = текущая оценка − стоимость приобретения.
- **Регулярные шаблоны** (`RecurringTemplate`): management-команда `run_recurring`
  создаёт транзакции по активным шаблонам в указанный день месяца.
- **Аналитика** (`analytics/services.py`): `calculate_pnl(user, date_from, date_to)`
  и `calculate_net_worth(user, as_of_date)` — агрегирующие ORM-запросы.
- **Дашборд**: карточки Net Worth / P&L за месяц, график динамики капитала (Chart.js),
  последние транзакции.
- **Статистика**: фильтр периода, pie-диаграммы по категориям, таблица доходы/расходы
  за последние 12 месяцев.
- **Импорт/экспорт CSV**: экспорт каждой сущности и полный экспорт в ZIP, импорт с
  валидацией структуры, построчным отчётом об ошибках и upsert-логикой.
- **Безопасность**: строгая фильтрация по `request.user` (`OwnerQuerySetMixin`), CSRF,
  хеширование паролей Django, продакшн-настройки HTTPS при `DEBUG=False`.

## Стек

- Python 3.10+, Django 4.2
- Django Templates + HTMX/Alpine.js + Bootstrap 5 + Chart.js
- БД: **SQLite** по умолчанию (без зависимостей), **PostgreSQL** через `DATABASE_URL`
- `django-crispy-forms` + `crispy-bootstrap5`

## Установка и запуск

```bash
# 1. Виртуальное окружение (опционально)
python -m venv venv
venv\Scripts\activate          # Windows
# source venv/bin/activate     # Linux/macOS

# 2. Зависимости
pip install -r requirements.txt

# 3. Создайте .env (опционально; значения по умолчанию подходят для локального запуска)
#    SECRET_KEY=...
#    DEBUG=True
#    DATABASE_URL=postgres://user:pass@localhost:5432/fintable   # без строки — SQLite

# 4. Миграции
python manage.py migrate

# 5. Суперпользователь
python manage.py createsuperuser

# 6. Dev-сервер
python manage.py runserver
```

Приложение доступно по адресу `http://127.0.0.1:8000/`. Админка — `/admin/`.

### Регулярные операции (cron)

Запускать ежедневно (например, в 01:00):

```bash
python manage.py run_recurring              # за сегодня
python manage.py run_recurring --date 2026-08-22
```

Пример cron (Linux): `0 1 * * * cd /path/to/FinTable && venv/bin/python manage.py run_recurring`.
На Windows — через Task Scheduler, запуская `run_recurring` раз в сутки.

## Тесты

```bash
python manage.py test
```

Покрытие: расчёт накопленного дохода по вкладу (simple и compound), расчёт P&L,
изоляция данных между двумя пользователями, создание дефолтных категорий.

## Структура проекта

```
fintable/         настройки проекта, urls
accounts/         User (email-логин), auth views
finance/          Account, Category, Transaction, RecurringTemplate,
                  forms, views, mixins, templatetags, management/commands
deposits/         Deposit (get_accrued_income, current_balance, close)
securities/       Security, SecurityValuation
analytics/        services.py (calculate_pnl, calculate_net_worth, динамика),
                  views (dashboard, stats), tests
importexport/     spec.py (CSV-спецификация, экспорт, импорт, upsert), views
templates/        base.html + шаблоны по приложениям
```

## Формат импорта/экспорта CSV

- Разделитель: `;`, кодировка UTF-8 (с BOM для корректного открытия в Excel).
- Первая строка — заголовки (человекочитаемые, см. ниже); порядок важен.
- Дата: ISO 8601 (`YYYY-MM-DD`).
- Числа: десятичная точка (например `1200000.00`), запятая автоматически нормализуется.
- Булевы поля: `1`/`0`.
- Поля с типом `choice` импортируются по человекочитаемому значению
  (например «Карта», «Доход») либо по машинному ключу (`card`, `income`).
- Внешние ключи задаются человекочитаемым полем (название счёта/категории/бумаги),
  связывание выполняется в рамках текущего пользователя.
- Upsert: существующие записи ищутся по ключевым полям (указаны в скобках у имени файла)
  и обновляются, отсутствующие — создаются. Поля `user`/`id` пользователя не пишутся в CSV.

### Колонки по сущностям

**accounts.csv** (upsert: `name`) — `Название`; `Тип`(Карта/Наличные/Другое); `Активен`(bool, необ.).

**categories.csv** (upsert: `name,type`) — `Название`; `Тип`(Доход/Расход); `Активна`(bool, необ.).

**transactions.csv** (upsert: `account,category,amount,date`) — `Счёт`; `Категория`;
`Сумма`(decimal); `Тип`(Доход/Расход); `Дата`(ISO); `Описание`(необ.).

**deposits.csv** (upsert: `name`) — `Название`; `Счёт`(необ.); `Тело вклада`(decimal);
`Годовая ставка %`(decimal); `Дата начала`(ISO); `Капитализация`
(Простой процент/Ежемесячная капитализация); `Статус`(Активен/Закрыт, необ.);
`Дата закрытия`(ISO, необ.).

**securities.csv** (upsert: `name`) — `Название`; `Стоимость приобретения`(decimal);
`Количество/доля`(decimal, необ.); `Дата приобретения`(ISO).

**security_valuations.csv** (upsert: `security,date`) — `Бумага`; `Оценка`(decimal); `Дата`(ISO).

**recurring.csv** (upsert: `category,account,amount,day_of_month`) — `Категория`; `Счёт`;
`Сумма`(decimal); `Тип`(Доход/Расход); `День месяца`(int); `Описание`(необ.); `Активен`(bool, необ.).


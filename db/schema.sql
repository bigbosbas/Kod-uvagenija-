-- Схема Postgres для лендинга «Код уважения».
-- Безопасно перезапускать: все команды идемпотентны (IF NOT EXISTS).
-- Прогонять вручную через psql/панель Timeweb DBaaS — отдельного инструмента миграций нет,
-- как и на вебинарном проекте.

create extension if not exists pgcrypto;

create table if not exists payments (
  id uuid primary key default gen_random_uuid(),
  created_at timestamptz not null default now(),
  order_id text not null unique,       -- InvId, который передаём в Робокассу
  email text,
  amount numeric(10,2) not null,
  status text not null default 'pending'
    check (status in ('pending', 'paid', 'failed')),
  robokassa_payload jsonb,             -- сырой callback от Робокассы, для аудита/споров
  paid_at timestamptz,
  access_token text,                   -- приватный токен доступа к PDF (?access=<token>)
  access_source text not null default 'auto'
    check (access_source in ('auto', 'manual')),
  granted_by text,                     -- кто выдал вручную (для manual), иначе null
  notes text
);

-- CREATE TABLE IF NOT EXISTS не добавляет колонки в уже существующую таблицу —
-- это уже был кейс на живой базе «Кода уважения», добавляем явно и идемпотентно.
-- Оба лендинга («Код уважения» и «Пересборка») делят один магазин Robokassa
-- и один вебхук — платежи различаются пользовательским параметром Shp_product.
-- 'kod' — значение по умолчанию для уже существующих записей.
alter table payments add column if not exists product text not null default 'kod';
alter table payments drop constraint if exists payments_product_check;
alter table payments add constraint payments_product_check check (product in ('kod', 'peresborka'));

-- Для 'peresborka' сюда пишется одноразовая Telegram-инвайт-ссылка вместо
-- presigned S3-URL — доступ к материалам через приватный канал, не файл.
alter table payments add column if not exists telegram_invite_link text;

create index if not exists payments_product_idx on payments (product);

create index if not exists payments_status_idx on payments (status);
create index if not exists payments_created_at_idx on payments (created_at desc);

create unique index if not exists payments_access_token_idx
  on payments (access_token)
  where access_token is not null;

-- Админка: один общий пароль, хранится как хеш в базе (не в .env),
-- чтобы заказчик мог сам сменить его из интерфейса. См. ТЗ, раздел 5.
create table if not exists admin_credentials (
  id int primary key default 1,
  password_hash text not null,
  updated_at timestamptz not null default now(),
  constraint single_row check (id = 1)
);

create table if not exists admin_login_attempts (
  id uuid primary key default gen_random_uuid(),
  created_at timestamptz not null default now(),
  ip text not null,
  success boolean not null
);

create index if not exists admin_login_attempts_ip_created_idx
  on admin_login_attempts (ip, created_at desc);

-- Лог визитов и UTM-меток для статистики в админке (перенесено с вебинарного
-- проекта). IP хранится только как хеш — не как plain text (минимизация ПДн).
create table if not exists visits (
  id uuid primary key default gen_random_uuid(),
  created_at timestamptz not null default now(),
  utm_source text,
  utm_medium text,
  utm_campaign text,
  utm_content text,
  utm_term text,
  referrer text,
  landing_path text,
  user_agent text,
  ip_hash text
);

create index if not exists visits_created_at_idx on visits (created_at desc);
create index if not exists visits_utm_source_idx on visits (utm_source);

-- Тот же общий сервер обслуживает оба лендинга (см. payments.product выше) —
-- без этой колонки визиты с двух разных доменов/UTM-кампаний смешивались бы
-- в статистике без возможности разделить источники по продукту.
alter table visits add column if not exists product text not null default 'kod';
alter table visits drop constraint if exists visits_product_check;
alter table visits add constraint visits_product_check check (product in ('kod', 'peresborka'));
create index if not exists visits_product_idx on visits (product);

-- Kegel PostgreSQL 表结构。与原 SQLite 版逐列对应：列名、语义、约束、索引不变，
-- 仅把存储类型映射为 PostgreSQL 等价类型，自增主键改为雪花 ID（应用侧生成的 BIGINT）。
-- 幂等：可重复执行。  psql "$DATABASE_URL" -f sql/schema.sql

CREATE TABLE IF NOT EXISTS checkin_settings (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS days (
    day         TEXT PRIMARY KEY,
    opened_at   DOUBLE PRECISION,
    open_reason TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS visits (
    id         BIGINT PRIMARY KEY,
    day        TEXT NOT NULL,
    subject    TEXT NOT NULL,
    username   TEXT NOT NULL,
    visitor    TEXT NOT NULL,
    ip_hash    TEXT NOT NULL,
    kind       TEXT NOT NULL,
    created_at DOUBLE PRECISION NOT NULL
);
CREATE INDEX IF NOT EXISTS visits_subject_time ON visits(subject, created_at);
CREATE INDEX IF NOT EXISTS visits_day ON visits(day);

CREATE TABLE IF NOT EXISTS reviews (
    day      TEXT NOT NULL,
    user_id  TEXT NOT NULL,
    reason   TEXT NOT NULL,
    approved INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (day, user_id)
);

CREATE TABLE IF NOT EXISTS sessions (
    day              TEXT NOT NULL,
    user_id          TEXT NOT NULL,
    token            TEXT NOT NULL,
    step             INTEGER NOT NULL DEFAULT 0,
    updated_at       DOUBLE PRECISION NOT NULL,
    expires_at       DOUBLE PRECISION NOT NULL,
    min_seconds      INTEGER NOT NULL,
    flow_id          TEXT NOT NULL DEFAULT '',
    eligible         INTEGER NOT NULL DEFAULT 0,
    mode             TEXT NOT NULL DEFAULT 'manual',
    repetitions      INTEGER NOT NULL DEFAULT 3,
    interval_seconds INTEGER,
    PRIMARY KEY (day, user_id)
);

CREATE TABLE IF NOT EXISTS entries (
    day           TEXT NOT NULL,
    user_id       TEXT NOT NULL,
    username      TEXT NOT NULL,
    rank          INTEGER NOT NULL,
    amount        BIGINT NOT NULL CHECK (amount >= 0),
    completed_at  DOUBLE PRECISION NOT NULL,
    claimed_at    DOUBLE PRECISION,
    reward_status TEXT NOT NULL CHECK (reward_status IN ('unclaimed', 'credited', 'none')),
    flow_id       TEXT,
    PRIMARY KEY (day, user_id),
    UNIQUE (day, rank)
);

CREATE TABLE IF NOT EXISTS points_wallets (
    user_id  TEXT PRIMARY KEY,
    username TEXT NOT NULL,
    balance  BIGINT NOT NULL DEFAULT 0 CHECK (balance >= 0 AND balance <= 9000000000000000)
);

CREATE TABLE IF NOT EXISTS points_ledger (
    id            BIGINT PRIMARY KEY,
    user_id       TEXT NOT NULL REFERENCES points_wallets(user_id),
    kind          TEXT NOT NULL,
    reference     TEXT NOT NULL,
    delta         BIGINT NOT NULL CHECK (delta != 0),
    balance_after BIGINT NOT NULL,
    created_at    DOUBLE PRECISION NOT NULL,
    UNIQUE (kind, reference)
);
CREATE INDEX IF NOT EXISTS ledger_user ON points_ledger(user_id, id);

CREATE TABLE IF NOT EXISTS practice_triggers (
    id          BIGINT PRIMARY KEY,
    day         TEXT NOT NULL,
    user_id     TEXT NOT NULL,
    username    TEXT NOT NULL,
    flow_id     TEXT NOT NULL,
    group_no    INTEGER NOT NULL,
    min_seconds INTEGER NOT NULL,
    created_at  DOUBLE PRECISION NOT NULL,
    mode        TEXT NOT NULL DEFAULT 'manual',
    repetitions INTEGER NOT NULL DEFAULT 3,
    UNIQUE (flow_id, group_no)
);
CREATE INDEX IF NOT EXISTS practice_day ON practice_triggers(day, id);

CREATE TABLE IF NOT EXISTS training_records (
    id               BIGINT PRIMARY KEY,
    user_id          TEXT NOT NULL,
    username         TEXT NOT NULL,
    day              TEXT NOT NULL,
    round_id         TEXT NOT NULL,
    started_at       BIGINT NOT NULL,
    ended_at         BIGINT NOT NULL,
    repetitions      INTEGER NOT NULL CHECK (repetitions BETWEEN 1 AND 20),
    interval_seconds INTEGER NOT NULL CHECK (interval_seconds BETWEEN 2 AND 10),
    mode             TEXT NOT NULL CHECK (mode IN ('manual', 'auto')),
    received_at      BIGINT NOT NULL,
    UNIQUE (user_id, round_id),
    CHECK (started_at < ended_at)
);
CREATE INDEX IF NOT EXISTS training_records_day ON training_records(day, received_at, user_id);
CREATE INDEX IF NOT EXISTS training_records_user_time ON training_records(user_id, started_at, ended_at);
CREATE INDEX IF NOT EXISTS training_records_user_latest ON training_records(user_id, received_at DESC, id DESC);

CREATE TABLE IF NOT EXISTS shop_products (
    id               BIGINT PRIMARY KEY,
    category         TEXT NOT NULL DEFAULT 'LDC',
    name             TEXT NOT NULL,
    description      TEXT NOT NULL DEFAULT '',
    points_price     BIGINT NOT NULL CHECK (points_price >= 0),
    ldc_amount       TEXT NOT NULL DEFAULT '1.00',
    user_daily_limit INTEGER NOT NULL DEFAULT 0 CHECK (user_daily_limit >= 0),
    total_daily_limit INTEGER NOT NULL DEFAULT 0 CHECK (total_daily_limit >= 0),
    is_active        INTEGER NOT NULL CHECK (is_active IN (0, 1))
);

CREATE TABLE IF NOT EXISTS shop_purchases (
    order_no     TEXT PRIMARY KEY,
    product_id   BIGINT NOT NULL REFERENCES shop_products(id),
    category     TEXT NOT NULL,
    product_name TEXT NOT NULL,
    user_id      TEXT NOT NULL,
    username     TEXT NOT NULL,
    points_cost  BIGINT NOT NULL,
    ldc_amount   TEXT NOT NULL,
    status       TEXT NOT NULL CHECK (status IN ('pending', 'success', 'simulated', 'failed', 'uncertain')),
    trade_no     TEXT NOT NULL DEFAULT '',
    error        TEXT NOT NULL DEFAULT '',
    created_at   DOUBLE PRECISION NOT NULL,
    day          TEXT NOT NULL,
    request_id   TEXT
);
CREATE UNIQUE INDEX IF NOT EXISTS shop_purchases_request ON shop_purchases(user_id, request_id);
CREATE INDEX IF NOT EXISTS shop_purchases_user ON shop_purchases(user_id, created_at);
CREATE INDEX IF NOT EXISTS shop_purchases_day ON shop_purchases(day, product_id);

CREATE TABLE IF NOT EXISTS donation_orders (
    order_no     TEXT PRIMARY KEY,
    user_id      TEXT NOT NULL,
    username     TEXT NOT NULL,
    amount_cents BIGINT NOT NULL CHECK (amount_cents > 0 AND amount_cents <= 1000000),
    pid          TEXT NOT NULL,
    name         TEXT NOT NULL,
    created_at   DOUBLE PRECISION NOT NULL
);
CREATE INDEX IF NOT EXISTS donation_orders_user ON donation_orders(user_id, created_at);

CREATE TABLE IF NOT EXISTS donation_settlements (
    order_no TEXT PRIMARY KEY REFERENCES donation_orders(order_no),
    trade_no TEXT NOT NULL UNIQUE,
    paid_at  DOUBLE PRECISION NOT NULL
);

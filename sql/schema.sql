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

-- ── 称号抽卡（机制见 docs/title_gacha_v2.md；不含任何具体卡名）──────────────────
-- 机制层卡位：code 为稳定主键（如 SSR-03），展示信息放 title_content。
CREATE TABLE IF NOT EXISTS title_defs (
    id            BIGINT PRIMARY KEY,
    code          TEXT UNIQUE NOT NULL,
    rarity        TEXT NOT NULL CHECK (rarity IN ('N','R','SR','SSR','UR')),
    weight        INTEGER NOT NULL DEFAULT 1 CHECK (weight > 0),
    discount_bp   INTEGER NOT NULL DEFAULT 10000 CHECK (discount_bp BETWEEN 9000 AND 10000),
    is_active     INTEGER NOT NULL DEFAULT 1 CHECK (is_active IN (0,1)),
    is_limited    INTEGER NOT NULL DEFAULT 0 CHECK (is_limited IN (0,1)),
    is_smeltable  INTEGER NOT NULL DEFAULT 1 CHECK (is_smeltable IN (0,1)),
    created_at    DOUBLE PRECISION NOT NULL
);

-- 展示层：名称/描述/图标/路线，可独立替换，不影响机制。
CREATE TABLE IF NOT EXISTS title_content (
    title_id      BIGINT PRIMARY KEY REFERENCES title_defs(id),
    name          TEXT NOT NULL DEFAULT '',
    description   TEXT NOT NULL DEFAULT '',
    icon          TEXT NOT NULL DEFAULT '',
    route         TEXT NOT NULL DEFAULT '',
    source_type   TEXT NOT NULL DEFAULT 'generated' CHECK (source_type IN ('badge','generated')),
    updated_at    DOUBLE PRECISION NOT NULL
);

CREATE TABLE IF NOT EXISTS user_titles (
    user_id           TEXT NOT NULL,
    title_id          BIGINT NOT NULL REFERENCES title_defs(id),
    copies            INTEGER NOT NULL CHECK (copies > 0),
    first_obtained_at DOUBLE PRECISION NOT NULL,
    last_obtained_at  DOUBLE PRECISION NOT NULL,
    PRIMARY KEY (user_id, title_id)
);

-- 三种独立面额券余额 + 保底/抽数统计。
CREATE TABLE IF NOT EXISTS user_title_state (
    user_id            TEXT PRIMARY KEY,
    equipped_title_id  BIGINT REFERENCES title_defs(id),
    tickets_single     INTEGER NOT NULL DEFAULT 0 CHECK (tickets_single >= 0),
    tickets_ten        INTEGER NOT NULL DEFAULT 0 CHECK (tickets_ten >= 0),
    tickets_hundred    INTEGER NOT NULL DEFAULT 0 CHECK (tickets_hundred >= 0),
    pity               INTEGER NOT NULL DEFAULT 0 CHECK (pity >= 0),
    total_draws        BIGINT NOT NULL DEFAULT 0
);

-- 抽卡批次：券型与抽数绑定，request_id 幂等。
CREATE TABLE IF NOT EXISTS title_draw_batches (
    id           BIGINT PRIMARY KEY,
    user_id      TEXT NOT NULL,
    request_id   TEXT NOT NULL,
    ticket_type  TEXT NOT NULL CHECK (ticket_type IN ('single','ten','hundred')),
    count        INTEGER NOT NULL CHECK (count IN (1,10,100)),
    created_at   DOUBLE PRECISION NOT NULL,
    UNIQUE (user_id, request_id),
    CHECK ((ticket_type='single' AND count=1)
        OR (ticket_type='ten'    AND count=10)
        OR (ticket_type='hundred' AND count=100))
);

CREATE TABLE IF NOT EXISTS title_draws (
    id          BIGINT PRIMARY KEY,
    batch_id    BIGINT NOT NULL REFERENCES title_draw_batches(id),
    user_id     TEXT NOT NULL,
    title_id    BIGINT NOT NULL REFERENCES title_defs(id),
    rarity      TEXT NOT NULL,
    is_new      INTEGER NOT NULL CHECK (is_new IN (0,1)),
    pity_before INTEGER NOT NULL,
    created_at  DOUBLE PRECISION NOT NULL
);
CREATE INDEX IF NOT EXISTS title_draws_user ON title_draws(user_id, id DESC);

CREATE TABLE IF NOT EXISTS title_crafts (
    id               BIGINT PRIMARY KEY,
    user_id          TEXT NOT NULL,
    kind             TEXT NOT NULL CHECK (kind IN ('smelt_random','smelt_target','ur')),
    input_rarity     TEXT,
    output_title_id  BIGINT NOT NULL REFERENCES title_defs(id),
    materials        JSONB NOT NULL DEFAULT '[]'::jsonb,
    request_id       TEXT NOT NULL,
    created_at       DOUBLE PRECISION NOT NULL,
    UNIQUE (user_id, request_id)
);

-- 券流水：按券型分账；UNIQUE 保证 checkin:{day} 等来源幂等。
CREATE TABLE IF NOT EXISTS title_ticket_ledger (
    id            BIGINT PRIMARY KEY,
    user_id       TEXT NOT NULL,
    ticket_type   TEXT NOT NULL CHECK (ticket_type IN ('single','ten','hundred')),
    delta         INTEGER NOT NULL,
    reason        TEXT NOT NULL,
    reference     TEXT NOT NULL,
    balance_after INTEGER NOT NULL,
    created_at    DOUBLE PRECISION NOT NULL,
    UNIQUE (user_id, ticket_type, reason, reference)
);
CREATE INDEX IF NOT EXISTS title_ticket_ledger_user ON title_ticket_ledger(user_id, id DESC);

CREATE TABLE IF NOT EXISTS title_config (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

-- 券商品复用 shop_products（category='TICKET'，draw_count 标面额）；订单快照与折扣审计字段。
ALTER TABLE shop_products ADD COLUMN IF NOT EXISTS draw_count INTEGER NOT NULL DEFAULT 0;
ALTER TABLE shop_purchases ADD COLUMN IF NOT EXISTS draw_count INTEGER NOT NULL DEFAULT 0;
ALTER TABLE shop_purchases ADD COLUMN IF NOT EXISTS points_cost_original BIGINT;
ALTER TABLE shop_purchases ADD COLUMN IF NOT EXISTS points_discount_bp INTEGER NOT NULL DEFAULT 10000;
ALTER TABLE shop_purchases ADD COLUMN IF NOT EXISTS points_discount_saved BIGINT NOT NULL DEFAULT 0;

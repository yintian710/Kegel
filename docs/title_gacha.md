# 称号抽卡与熔炼系统方案

> 状态：设计稿，待实现  
> 日期：2026-11-04
> 范围：称号卡池、抽卡、签到券、熔炼/合成、UR、LDC 兑换折扣、后台管理  
> 原则：称号不可出售、交易、赠送或兑换积分，只能按规则熔炼/合成消耗；所有抽卡与合成结果由服务端决定。

---

## 1. 目标

1. 给站内积分增加一个长期消耗入口：抽称号。
2. 给每日打卡增加一个轻量奖励：签到抽卡券，让 51 名以后也能参与。
3. 用熔炼/合成消化重复与低稀有度称号，避免“抽到重复就废”。
4. 用 UR 作为长期毕业目标，并提供 LDC 兑换 95 折权益。
5. 完全复用现有积分钱包、流水、`write_txn()`、全局咨询锁和 `request_id` 幂等机制。

---

## 2. 等级与卡池

### 2.1 等级

采用 5 个等级；4 个 UR 是同一等级的 4 张不同称号，不是 4 个等级。

| 内部等级 | 中文显示 | 颜色 | 获取方式 |
|---|---|---|---|
| N | 普通 | 白 | 抽卡 |
| R | 稀有 | 绿 | 抽卡 |
| SR | 史诗 | 蓝 | 抽卡 |
| SSR | 传说 | 紫 | 抽卡 |
| UR | 至尊 | 金 / 红 | 合成限定 |

不建议增加第 6 个等级。更多等级只会让掉落表、熔炼比例和 UI 变复杂。

### 2.2 首发数量

| 稀有度 | 数量 | 总权重 | 单张概率 |
|---|---:|---:|---:|
| N | 50 | 60% | 1.200% |
| R | 30 | 28% | 0.933% |
| SR | 20 | 9% | 0.450% |
| SSR | 7 | 3% | 0.429% |
| UR | 4 | 0 | 合成限定 |
| **合计** | **111** | **100%** | |

- 每个稀有度内部等权；权重由后台维护。
- 单张 SR 与单张 SSR 概率接近是正常的：SR 有 20 张，SSR 只有 7 张，稀有度总量仍相差 3 倍。
- UR 不进抽卡池。
- 后续扩池按季度增加；新增称号不改表结构，只加 `title_defs` 行。

### 2.3 称号字段

- `code`：稳定唯一标识，逻辑不依赖展示名。
- `name`、`description`：展示文本，前端按纯文本渲染，禁止 HTML。
- `rarity`：`N/R/SR/SSR/UR`。
- `weight`：同稀有度内的抽取权重，正整数。
- `discount_bp`：LDC 兑换折扣，`10000` 为无折扣，`9500` 为 95 折。
- `is_active`：下架后不再掉落，已拥有仍保留。
- `is_limited`：限定称号，是否可熔炼由 `is_smeltable` 单独控制。
- `is_smeltable`：UR 必须为 0；限定称号可设为 0。

---

## 3. 抽卡与签到券

### 3.1 价格

| 方式 | 价格 | 说明 |
|---|---:|---|
| 单抽 | 50 积分 或 1 张抽卡券 | 优先用券 |
| 十连 | 475 积分 或 10 张抽卡券 | 积分价 95 折 |
| 混合支付 | 不允许 | 要么全券，要么全积分 |

- 1000 积分 = 20 抽；如果买 2 个十连（950）再单抽一次，是 21 抽。
- 抽卡券不能兑换积分，积分也不能直接购买抽卡券；积分直接作为抽卡货币。
- 券和积分抽卡都计入保底、`total_draws` 和抽卡历史。

### 3.2 签到券

| 来源 | 数量 | 说明 |
|---|---:|---|
| 每日完成打卡 | 1 张 | 基础券，替代“每日免费一抽” |
| 连续 3 天 | +1 张 | 第 3 天额外发放 |
| 连续 7 天 | +2 张 | 第 7 天额外发放 |
| 每周上限 | 12 张 | 防止无限囤积 |
| 持有上限 | 20 张 | 到顶后新券不叠加，页面提示 |
| 排名额外券 | 不发 | 排名已经发积分，避免富者愈富 |

- 约 **45 张/月**（1.5 张/天），相当于 2,250 积分的抽卡价值；这是及时使用时的数量。
- 券不过期；达到持有上限 20 张后，新券作废并提示，所以不建议长期囤券。
- 签到券在“完成打卡且生成 `entries` 记录”时发放，51 名以后也发；待审核期间不发，审核通过后按当天补发。
- 发券使用 `title_ticket_ledger`，`UNIQUE(user_id, reason, reference)` 保证同一用户同一 `checkin:{day}` 只发一次。
- 连签天数按 `entries` 的连续日期计算；也可在 `user_title_state` 维护 `checkin_streak` 与 `last_checkin_day`。

### 3.3 每日抽卡上限

- 默认 **50 抽/人/天**（券 + 积分合计），由 `title_config` 配置。
- 防止顶榜玩家囤积积分后一天爆发刷完，也防止脚本高频请求。
- 达到上限后返回 409，并提示“今日抽卡次数已用完”。

---

## 4. 概率与保底

### 4.1 基础概率

| 稀有度 | 基础概率 |
|---|---:|
| N | 60% |
| R | 28% |
| SR | 9% |
| SSR | 3% |
| UR | 0% |

### 4.2 保底

- **80 抽硬保底 SSR**：连续 80 抽没有 SSR 时，第 80 抽强制 SSR。
- 出 SSR 后 `pity` 重置为 0；任何稀有度、任何支付方式都计入 `pity`。
- 基础 SSR 3%，含 80 抽保底的综合 SSR 约 **3.3%**。
- 若后台没有可用的 SSR 称号，保底自动禁用并在管理页告警；抽卡接口仍可工作，但需明确提示。

### 4.3 20 抽期望

1000 积分 = 20 抽，从 0 保底开始：

| 稀有度 | 期望个数 | 至少 1 个的概率 |
|---|---:|---:|
| N | 12.0 | 约 100% |
| R | 5.6 | 99.9% |
| SR | 1.8 | 84.8% |
| SSR | 0.6 | 45.6% |

- 约 54.4% 的 1000 分批次没有 SSR。
- 约 15.2% 的 1000 分批次没有 SR。
- 如果已有 60+ 保底进度，20 抽会触发 SSR，实际结果更好。

### 4.4 十连 SR 保底（可选，默认关闭）

- 若开启：十连如果没有 SR 及以上，则最后一抽强制 SR；如果最后一抽本来出了 SSR，则保留 SSR，不降级。
- 开启后 SR 综合概率约 **11.8%**，SSR 仍约 3%；必须在概率公示中写“十连保底 SR，综合 SR 约 11.8%”。
- 默认关闭，以保持公示概率与基础概率一致；是否开启由运营决定。

### 4.5 随机数

- 只用服务端 `secrets.randbelow`，不信任客户端传入的任何结果或种子。
- 每个称号的抽取概率 = 该称号 `weight` / 同稀有度总权重。
- 权重变更只影响未来抽取；`title_draws` 保存抽到时的稀有度快照。

---

## 5. 熔炼与合成

### 5.1 比例

| 操作 | 随机 | 定向 |
|---|---:|---:|
| N → R | 3 张 N | 6 张 N |
| R → SR | 3 张 R | 6 张 R |
| SR → SSR | 5 张 SR | 10 张 SR |
| UR | — | 3 张指定 SSR（消耗）→ 1 张 UR |

等价关系（不计随机与重复）：

- **45 张 N = 1 张随机 SSR**（3 × 3 × 5）
- **360 张 N = 1 张指定 SSR**（6 × 6 × 10）

### 5.2 材料规则

- 熔炼材料必须是**同一稀有度**的称号副本；UR 合成材料必须与对应配方完全一致。
- 不要求熔炼材料同名；UR 合成则固定消耗 3 种不同的指定 SSR，各 1 张。
- 材料由用户显式勾选；服务端校验数量、稀有度、副本数和装备状态，不能静默自动消耗最后一张。
- 熔炼和合成都不可逆；界面必须显示“将消耗哪些称号、哪些会从图鉴消失”，并二次确认。
- 随机熔炼优先产出未拥有的目标；该档全部拥有时给随机重复副本。
- 定向熔炼可以选任意同档下一等级的在售称号；已拥有则变为副本，界面需提示。
- 熔炼/合成结果、消耗材料、时间写入 `title_crafts`，用于审计和幂等。

### 5.3 最后一张与装备

- **未装备的称号可以熔炼或合成消耗到最后一张，甚至 0 张**；到 0 时删除 `user_titles` 行，该称号从图鉴移除，重新抽到才算再次拥有。
- **装备中的称号至少保留 1 张**：`可消耗数量 = copies - (已装备 ? 1 : 0)`。
- 装备中的重复副本可以作为材料；不能消耗装备本体。若要使用最后一张，必须先卸下。
- UR 不可熔炼。
- SSR 被合成消耗后，其余依赖该 SSR 的 UR 配方按剩余副本数重新显示缺口。

### 5.4 UR 配方

首发 4 个 UR、7 个 SSR。每个 UR 固定消耗 3 种指定 SSR，各 1 张；同一个 SSR 可以参与多个配方，但每次合成都必须再次提供副本。

| UR | 消耗的 3 种指定 SSR | 组合含义 |
|---|---|---|
| 破界者 | 金笔杆 + 非凡贡献者 + 远见者 | 创作表达 + 实际贡献 + 前瞻判断 |
| 海纳百川 | 金笔杆 + 解题家 + 共情者 | 表达观点 + 分享知识 + 理解他人 |
| 浴火重生 | 共情者 + 虔行者 + 元气满满 | 支持与被支持 + 长期坚持 + 重新出发 |
| 领袖 | 非凡贡献者 + 解题家 + 虔行者 | 做出贡献 + 解决问题 + 长期承担 |

4 个 UR 的累计材料需求：

| SSR | 总需求 | 用于 UR |
|---|---:|---|
| 金笔杆 | 2 | 破界者、海纳百川 |
| 非凡贡献者 | 2 | 破界者、领袖 |
| 解题家 | 2 | 海纳百川、领袖 |
| 共情者 | 2 | 海纳百川、浴火重生 |
| 虔行者 | 2 | 浴火重生、领袖 |
| 元气满满 | 1 | 浴火重生 |
| 远见者 | 1 | 破界者 |

- 做完 4 个 UR 共消耗 12 张 SSR；不是集齐 7 种后永久解锁。
- 每个 UR 账号唯一；已拥有该 UR 时不能再合成，返回 409，且不得扣除材料。
- UR 合成后不自动装备；用户自行选择装备。

---

## 6. UR 与 LDC 95 折

### 6.1 折扣范围

- 只影响商店 `category='LDC'` 的**积分价格**，不影响 LDC 到账数量。
- 不影响赞助、打卡奖励、抽卡价格、抽卡券。
- 4 个 UR 默认都配置 `discount_bp=9500`（95 折）；多个折扣称号不叠加，取最优折扣。
- 折扣**拥有即生效**，不要求装备；装备只影响展示。
- 如果只想让其中一个 UR 带折扣，把其余 UR 的 `discount_bp` 设为 `10000` 即可。

### 6.2 计算

```text
实付积分 = ceil(原积分价 × discount_bp / 10000)
500 分 × 9500 / 10000 = 475 分
333 分 × 9500 / 10000 = 317 分（向上取整）
```

### 6.3 每日节省上限

- 默认 `DAILY_DISCOUNT_SAVE_CAP=500` 积分/人/天；由后台或环境变量配置。
- 接近上限时按剩余额度**部分打折**：本单可省 80、今日还剩 50，则只省 50。
- 达到上限后，本日后续 LDC 兑换按原价。
- `failed` 订单不计入已省额度；退款/对账失败后额度释放。
- 只统计 `pending/success/simulated/uncertain` 状态，规则与 LDC 每日额度一致。

### 6.4 订单审计

`shop_purchases` 增加：

| 字段 | 含义 |
|---|---|
| `points_cost_original` | 折扣前积分价 |
| `points_discount_bp` | 本单使用的折扣（10000 / 9500） |
| `points_discount_saved` | 本单实际节省积分 |
| `points_cost` | 实际支付积分（保持原字段） |

- 退款按 `points_cost`（实付）退，不按原价退。
- 管理后台增加“今日折扣总节省”“UR 持有人数”统计。
- 折扣计算在 `_reserve` 事务内完成，服务端读取已拥有称号，不信任前端。

---

## 7. 经济与节奏

### 7.1 关键目标

按 7 种 SSR 等权、综合 SSR 概率约 3.3% 粗估；定向熔炼会缩短缺特定材料的时间：

| 目标 | 路径 | 约抽数 | 约积分 |
|---|---|---:|---:|
| 第一张 UR | 获得任一配方的 3 种 SSR 并消耗 | 约 205 | 约 10,250 |
| 4 张 UR | 满足 `2+2+2+2+2+1+1` 的指定 SSR 需求 | 约 830 | 约 41,500 |
| 全图鉴（不含 UR） | 不熔炼 | 882 | 44,100 |

### 7.2 每月抽数与时间

按 50 分/抽、约 45 张券/月、顶榜 1000 分/天计算：

| 玩家 | 每月抽数 | 第一张 UR | 4 张 UR | 全图鉴 |
|---|---:|---:|---:|---:|
| 顶榜 1–10 | 600 积分抽 + 45 券 = 645 | 约 10 天 | 约 39 天 | 约 42 天 |
| 中游 11–20 | 300 + 45 = 345 | 约 18 天 | 约 72 天 | 约 77 天 |
| 休闲 21–50 | 60 + 45 = 105 | 约 59 天 | 约 237 天 | 约 252 天 |
| 51+ | 45 券 | 约 137 天 | 约 553 天 | 约 588 天 |

说明：

- UR 是长期消耗目标；完成 4 个 UR 后，12 张 SSR 已从图鉴或副本中扣除。
- 定向 10 SR→SSR 是补齐指定材料的主要路径；它能显著降低随机重复带来的尾部时间。
- 熔炼会消耗低稀有度图鉴；收藏流应保留最后一张，冲 UR 的玩家则需要在图鉴与材料之间取舍。
- 上表是概率期望，不是保底承诺；实际完成时间受 SSR 重复分布和定向熔炼影响。

### 7.3 1000 分的产出

- 直接抽：12 N / 5.6 R / 1.8 SR / 0.6 SSR。
- 全熔炼（N→R 3、R→SR 3、SR→SSR 5）：约 **1.6 SSR**。
- 全熔炼会失去大量 N/R/SR 图鉴，适合冲 UR 的玩家；收藏流应保留最后一张。

---

## 8. 数据模型

所有表使用雪花 ID、`DOUBLE PRECISION` 时间戳和现有 `sql/schema.sql` 幂等风格。

### 8.1 `title_defs`

```sql
CREATE TABLE IF NOT EXISTS title_defs (
    id            BIGINT PRIMARY KEY,
    code          TEXT UNIQUE NOT NULL,
    name          TEXT NOT NULL,
    description   TEXT NOT NULL DEFAULT '',
    rarity        TEXT NOT NULL CHECK (rarity IN ('N','R','SR','SSR','UR')),
    weight        INTEGER NOT NULL CHECK (weight > 0),
    discount_bp   INTEGER NOT NULL DEFAULT 10000 CHECK (discount_bp BETWEEN 9000 AND 10000),
    is_active     INTEGER NOT NULL DEFAULT 1 CHECK (is_active IN (0,1)),
    is_limited    INTEGER NOT NULL DEFAULT 0 CHECK (is_limited IN (0,1)),
    is_smeltable  INTEGER NOT NULL DEFAULT 1 CHECK (is_smeltable IN (0,1)),
    created_at    DOUBLE PRECISION NOT NULL
);
```

### 8.2 `user_titles`

```sql
CREATE TABLE IF NOT EXISTS user_titles (
    user_id           TEXT NOT NULL,
    title_id          BIGINT NOT NULL REFERENCES title_defs(id),
    copies            INTEGER NOT NULL CHECK (copies > 0),
    first_obtained_at DOUBLE PRECISION NOT NULL,
    last_obtained_at  DOUBLE PRECISION NOT NULL,
    PRIMARY KEY (user_id, title_id)
);
```

- `copies` 至少 1；熔炼到 0 时删除该行。
- 装备中的称号由服务层保证至少保留 1 张。

### 8.3 `user_title_state`

```sql
CREATE TABLE IF NOT EXISTS user_title_state (
    user_id            TEXT PRIMARY KEY,
    equipped_title_id  BIGINT REFERENCES title_defs(id),
    tickets            INTEGER NOT NULL DEFAULT 0 CHECK (tickets >= 0),
    pity               INTEGER NOT NULL DEFAULT 0 CHECK (pity >= 0),
    total_draws        BIGINT NOT NULL DEFAULT 0,
    checkin_streak     INTEGER NOT NULL DEFAULT 0,
    last_checkin_day   TEXT NOT NULL DEFAULT ''
);
```

### 8.4 `title_draw_batches`

```sql
CREATE TABLE IF NOT EXISTS title_draw_batches (
    id          BIGINT PRIMARY KEY,
    user_id     TEXT NOT NULL,
    request_id  TEXT NOT NULL,
    count       INTEGER NOT NULL CHECK (count IN (1,10)),
    payment     TEXT NOT NULL CHECK (payment IN ('ticket','points')),
    cost        BIGINT NOT NULL DEFAULT 0,
    tickets_cost INTEGER NOT NULL DEFAULT 0,
    created_at  DOUBLE PRECISION NOT NULL,
    UNIQUE (user_id, request_id)
);
```

### 8.5 `title_draws`

```sql
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
```

### 8.6 `title_crafts`

```sql
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
```

- `materials` 保存 `[{title_id, count}]`，用于审计“消耗了哪些称号”。
- 同一 `request_id` 重试返回原结果，不重复消耗。

### 8.7 `title_ticket_ledger`

```sql
CREATE TABLE IF NOT EXISTS title_ticket_ledger (
    id            BIGINT PRIMARY KEY,
    user_id       TEXT NOT NULL,
    delta         INTEGER NOT NULL CHECK (delta <> 0),
    reason        TEXT NOT NULL,
    reference     TEXT NOT NULL,
    balance_after INTEGER NOT NULL,
    created_at    DOUBLE PRECISION NOT NULL,
    UNIQUE (user_id, reason, reference)
);
CREATE INDEX IF NOT EXISTS title_ticket_ledger_user ON title_ticket_ledger(user_id, id DESC);
```

### 8.8 `title_config`

```sql
CREATE TABLE IF NOT EXISTS title_config (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
```

保存抽卡价格、熔炼/合成成本、UR 配方、每日抽卡上限、每日折扣上限、签到券规则等；由后台维护并带校验。

### 8.9 商店表调整

```sql
ALTER TABLE shop_purchases ADD COLUMN IF NOT EXISTS points_cost_original BIGINT;
ALTER TABLE shop_purchases ADD COLUMN IF NOT EXISTS points_discount_bp INTEGER NOT NULL DEFAULT 10000;
ALTER TABLE shop_purchases ADD COLUMN IF NOT EXISTS points_discount_saved BIGINT NOT NULL DEFAULT 0;
```

历史订单的新增列为空或默认值；展示原价时用 `COALESCE(points_cost_original, points_cost)`，退款始终按 `points_cost`（实付）处理。

### 8.10 积分流水

- 积分抽卡：`points_ledger.kind='title_draw'`，`reference=batch_id`，现有 `UNIQUE(kind, reference)` 提供幂等。
- 券抽卡：不写积分流水，只写 `title_draw_batches.payment='ticket'`。
- 熔炼/合成：不写积分流水。
- 称号不能卖，因此不存在 `title_sale` 流水。

### 8.11 测试表清理

`tests/conftest.py` 的 `TABLES` 需加入：

```text
title_defs, user_titles, user_title_state, title_draw_batches,
title_draws, title_crafts, title_ticket_ledger, title_config
```

---

## 9. API

与商店一致：配置 OAuth 后，个人数据接口要求登录；访客可看卡池与概率，但不能抽卡。

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/titles` | 卡池、图鉴、装备、券、保底、配方、抽卡记录 |
| POST | `/api/titles/draw` | 抽卡，`count=1/10`、`payment=auto/ticket/points`、`request_id` |
| POST | `/api/titles/equip` | 装备/卸下，`title_id` 或 `null` |
| POST | `/api/titles/smelt` | 熔炼，`mode=random/target`、`input_rarity`、`target_title_id`、`materials`、`request_id` |
| POST | `/api/titles/craft` | UR 合成，`{recipe_id, materials, request_id}` |
| GET | `/api/titles/history` | 最近抽卡、熔炼、合成记录 |
| GET | `/api/shop` | 增加当前折扣、今日已省、剩余额度 |
| POST | `/api/shop/purchase` | 服务端自动应用折扣并写审计字段 |
| GET | `/api/admin/titles` | 管理后台称号列表 |
| POST | `/api/admin/titles` | 新建/修改称号、权重、折扣、可熔炼 |
| POST | `/api/admin/titles/grant` | 手动发放/收回称号（二级密码） |
| GET | `/api/admin/title-stats` | 抽卡、熔炼、UR、折扣统计 |

### 9.1 抽卡响应

```json
{
  "batch": {
    "id": "123",
    "count": 10,
    "payment": "points",
    "cost": 475,
    "tickets_cost": 0
  },
  "results": [
    {
      "title_id": "456",
      "name": "示例称号",
      "rarity": "SR",
      "is_new": true,
      "tickets_after": 3,
      "balance_after": 1525
    }
  ],
  "pity": 12,
  "pity_limit": 80,
  "wallet": { "balance": 1525 },
  "tickets": 3
}
```

### 9.2 熔炼响应

```json
{
  "kind": "smelt_random",
  "output": { "title_id": "789", "name": "新称号", "rarity": "SR", "is_new": true },
  "consumed": [
    { "title_id": "1", "count": 3 }
  ],
  "collection": { "copies": 0 }
}
```

---

## 10. 事务、并发与幂等

所有写操作在 `app/infrastructure/database.write_txn()` 内完成；现有全局 `pg_advisory_xact_lock` 串行化关键写流程。

### 10.1 抽卡

1. 校验登录、`count`、`payment`、`request_id` 格式。
2. 按 `(user_id, request_id)` 查询 `title_draw_batches`；存在且参数一致则原样返回，不重复扣费；参数不一致返回 409。
3. 校验每日抽卡上限。
4. `auto` 时先看券：足够则 `payment='ticket'`，否则用积分；券不够且积分不足返回 400。
5. 读取在售卡池，校验每个稀有度至少 1 个可用称号；SSR 为空时禁用保底并在管理页告警，不强制产出 SSR。
6. 逐抽计算：`pity += 1`；到 80 强制 SSR；否则按权重抽；记录 `pity_before`。
7. 首次获得插入/更新 `user_titles`；重复则 `copies += 1`。
8. 扣券（写 `title_ticket_ledger`，`reference=batch_id`）或扣积分（`credits.spend_points(..., 'title_draw', batch_id, now)`）。
9. 更新 `user_title_state.pity/total_draws`，插入批次与明细，提交。

### 10.2 熔炼/合成

1. 校验登录、`request_id`、材料格式。
2. 按 `(user_id, request_id)` 查询 `title_crafts`；存在且参数一致则返回原结果，参数不一致返回 409。
3. 读取材料称号，校验同稀有度、数量等于配方、`copies` 足够、未被装备到 0。
4. 消耗副本；`copies=0` 删除 `user_titles` 行。
5. 随机/定向选出产出；插入或增加 `user_titles`。
6. 写 `title_crafts`（含 `materials` 快照），提交。
7. UR 合成额外校验：已拥有该 UR 则 409；3 张指定 SSR 副本足够；配方共享关系正确。

### 10.3 签到发券

1. 打卡完成事务内，确认该用户有当天 `entries` 记录且不是待审核。
2. 计算连签天数；按规则计算本次券数：基础 1 + 3 天 +1 + 7 天 +2。
3. 检查周上限 12、持有上限 20；超出部分不发放。
4. 写 `title_ticket_ledger(reason='checkin', reference='checkin:{day}')`，唯一约束防重复。
5. 更新 `user_title_state.tickets/checkin_streak/last_checkin_day`。

### 10.4 装备

- 装备前确认 `user_titles.copies >= 1`；否则 409。
- 装备中的称号至少保留 1 张；所有熔炼/合成材料校验都要读取当前装备。
- 卸下允许；卸下后最后一张可以被熔炼。

---

## 11. 前端

### 11.1 `/titles` 页面

- 顶部：积分余额、抽卡券、保底进度（`pity/80`）、今日剩余抽数。
- 抽卡区：单抽（券/50 分）、十连（10 券/475 分）、概率公示、保底说明。
- 图鉴区：按稀有度分组，显示已拥有/副本数/装备状态；未拥有显示剪影。
- 熔炼/合成区：
  - 按稀有度显示可用副本；显式勾选材料。
  - 显示配方、产出预览、将失去的图鉴警告。
  - UR 配方显示 4 个 UR 的材料清单，红/绿标识缺口。
- 记录区：最近 50 次抽卡、熔炼、合成。
- 空状态/未登录：展示卡池与概率，抽卡按钮提示登录。

### 11.2 打卡页

- 完成打卡后显示“+1 抽卡券”；连签 3/7 天显示额外奖励。
- 显示连签进度和距离下一档还差几天。

### 11.3 商店

- 有折扣时显示横幅：“UR「XX」生效：LDC 兑换 95 折，今日还可省 X 积分”。
- 商品卡片显示原价、实付价、本单节省；达到上限显示“今日折扣额度已用完”。
- 无折扣时提示“拥有 UR 称号可享 LDC 兑换 95 折”。

### 11.4 榜单

- 打卡榜、训练榜用户名旁显示装备称号标签；UR 使用专属样式。
- 未装备则不显示；不额外做“隐藏称号”开关，卸下即可。

### 11.5 导航与路由

- 新增 `/titles` 路由，导航「称号」放在「商店」之后。
- 更新 `SiteNavigation.vue`、`router/index.ts`、`api/index.ts` 类型。

---

## 12. 管理后台

新增「称号管理」：

- 称号 CRUD：名称、描述、稀有度、权重、`discount_bp`、上架/下架、限定、可熔炼。
- 配方配置：熔炼随机/定向成本、UR 配方、每周/持有券上限、每日抽卡上限、每日折扣上限。
- 统计：抽卡次数、积分消耗、券消耗、各稀有度出货、SSR/UR 数量、UR 持有人数、每日折扣总节省。
- 手动发放/收回称号、调整券（需二级密码）。
- 校验：
  - 权重为正整数；每个在售稀有度至少 1 个称号。
  - 保底启用时必须有在售 SSR。
  - UR 必须 `is_smeltable=0`，且配方材料存在。
  - `discount_bp` 在 9000–10000（最低 9 折，防止误配成免费）；多折扣称号不叠加，后台提示当前最优折扣。
  - 修改权重/折扣只影响未来，历史 `title_draws`/`title_crafts` 保留快照。

---

## 13. 风控与合规

- **不可出售/交易/赠送/兑换积分**：没有出售接口，不写 `title_sale` 流水；称号是账号绑定资产。
- **概率公示**：页面展示各稀有度基础概率、单张概率、保底规则；开启十连 SR 保底时必须公示调整后的 SR 综合概率。
- **不开放充值抽卡**：抽卡券和积分只能来自打卡、排名奖励、管理员发放；不提供真实货币购买。
- **上限**：每日抽卡 50 次、券持有 20 张、每周签到券 12 张、LDC 折扣每日节省 500 积分。
- **审计**：所有抽卡、熔炼、合成、券发放留记录；管理员只能查看历史，不能改历史。
- **防小号**：签到券要求完成打卡；称号绑定、不可转移，开小号收益有限；仍建议按账号限流。
- **XSS**：称号名称/描述按纯文本渲染，禁止 HTML。
- **经济监控**：每日积分消耗、券发放、SSR/UR 数量、LDC 折扣节省、LDC 兑换量；异常时先降折扣/券量，再改权重。

---

## 14. 测试

至少覆盖：

1. 抽卡：单抽/十连、券优先、积分不足、券不足、`request_id` 幂等、重复请求不重复扣费。
2. 保底：第 80 抽强制 SSR、出 SSR 重置、券抽计入保底。
3. 每日上限：达到 50 抽后拒绝。
4. 图鉴/副本：首次 `is_new=1`，重复 `copies+1`。
5. 熔炼：随机/定向、同稀有度校验、数量校验、最后一张可熔炼、装备中至少留 1、熔炼到 0 删除。
6. UR：3 张指定 SSR 消耗、已拥有拒绝、材料不足拒绝、共享配方正确、4 个 UR 共需 12 张 SSR。
7. 签到券：基础 1 张、3 天 +1、7 天 +2、周上限 12、持有上限 20、`checkin:{day}` 幂等、待审核不发。
8. 折扣：UR 95 折、非 UR 原价、多 UR 不叠加、每日节省上限、部分折扣、退款释放额度、只影响 LDC。
9. 商店退款：按实付积分退，不按原价退。
10. 榜单：装备称号显示、未装备不显示、UR 样式。
11. 后台：权重/折扣/配方校验、手动发放/收回、统计。
12. 并发：两个相同 `request_id` 并发只生效一次；抽卡与熔炼不会出现负副本/负券。

---

## 15. 实施顺序

1. `sql/schema.sql` 新表 + `app/service/titles.py` + 抽卡/保底/券/熔炼/UR/折扣测试。
2. `/api/titles` + `/titles` 页面 + 导航/路由/类型。
3. 打卡完成发券 + 连签计算 + 打卡页展示。
4. 商店折扣接入 + `shop_purchases` 审计字段 + 商店 UI。
5. 装备展示 + 打卡榜/训练榜联表。
6. 管理后台称号管理 + 统计。
7. 上线后观察 2–4 周，调整权重、券量、UR 配方和折扣上限。

---

## 16. 待确认 / 可配置

| 项 | 默认 | 备选 |
|---|---|---|
| 十连 SR 保底 | 关闭 | 开启，公示 SR 综合约 11.8% |
| 4 个 UR 的 95 折 | 4 个都有 | 只有 1 个有，其余纯外观 |
| 每日抽卡上限 | 50 | 30 / 100 |
| UR 配方 | 3 张指定 SSR 消耗 | 调整指定配方；不提供免消耗模式 |
| 签到基础券 | 1 张/天 | 2 张/天 |
| 定向 SR→SSR | 10 张 SR | 15 张 SR |
| 卡池权重 | N60/R28/SR9/SSR3 | 后台可调 |

---

## 17. 验收标准

- 登录用户可以用积分或签到券抽卡，扣费、保底、副本、图鉴、记录全部正确。
- 签到完成能按规则发券，连签 3/7 天有额外券，重复请求不重复发。
- 未装备称号可以熔炼到最后一张并移出图鉴；装备中的称号至少保留 1 张。
- 4 个 UR 可按共享配方合成；材料不足/已拥有时有明确错误。
- UR 拥有者兑换 LDC 时自动 95 折，受每日节省上限约束；退款按实付积分退。
- 打卡榜/训练榜显示装备称号；管理后台可维护称号、权重、折扣、配方和统计。
- 概率、保底、券规则在页面上可查；所有写操作有幂等与审计记录。

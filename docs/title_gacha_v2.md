# 称号抽卡系统 · 机制设计稿 v2.1（不含卡名）

> 状态：新设计稿（机制优先版），待评审  
> 日期：2026-11-23（v2.1 修订）  
> 范围：稀有度与卡池结构、券式抽卡、购券、保底、签到送券、熔炼/合成、UR 权益（LDC 折扣）、数据模型、API、事务、前端、后台、合规、测试  
> 前置结论：**本文只定义机制，不包含任何具体称号名称、描述或图片**。卡名与文案由独立的《称号内容表》维护，机制层一律用 `稀有度-序号` 占位（如 `SSR-03`）。  
> 与旧稿关系：本文替代 `docs/title_gacha.md` 作为机制主稿；旧稿中的称号名单/路线含义/稀缺值仅作内容侧参考，不进入机制层。

## v2.1 相对 v2 的变更（本轮）

1. **抽卡只消耗券**，不再用积分直接抽卡。
2. **三种独立面额券**：单抽券（1 抽）、十连券（10 抽）、百连券（100 抽），各自整用，不可拆分、不可混用。
3. **券可用积分购买**；三种券作为后台商品配置（类目 `TICKET`，与 LDC 商品同一套配置与展示逻辑），价格后台设置。
4. **不设抽卡上限**，也不设券持有上限。
5. **购券不限购**，只受积分余额限制。
6. **打卡送券改为名额档位配置**：与积分 `reward_tiers` 同构、但**独立配置**（`ticket_reward_tiers`），每个名次档位指定送的券面额与数量，不再固定"1 张/天 + 连签"。

---

## 0. 阅读约定与占位符

### 0.1 五档稀有度

| 内部代号 | 中文显示 | 颜色 | 获取方式 |
|---|---|---|---|
| N | 普通 | 白 | 抽卡 |
| R | 稀有 | 绿 | 抽卡 |
| SR | 史诗 | 蓝 | 抽卡 |
| SSR | 传说 | 紫 | 抽卡 |
| UR | 至尊 | 金 / 红 | 合成限定 |

不增加第 6 档。

### 0.2 卡位占位符

- 抽卡池卡位：`N-01 … N-50`、`R-01 … R-30`、`SR-01 … SR-20`、`SSR-01 … SSR-07`。
- 合成限定卡位：`UR-01 … UR-04`，不进抽卡池。
- 占位符只是**稳定主键**，不是展示名；展示名来自《称号内容表》。
- 路线用 `路线 A … 路线 G` 表示，具体主题与命名由内容表决定。

### 0.3 券面额代码

| 券类型 | 代码 | 抽数 |
|---|---|---:|
| 单抽券 | `single` | 1 |
| 十连券 | `ten` | 10 |
| 百连券 | `hundred` | 100 |

三种券**相互独立**：各有独立余额、独立购买、独立消耗，不能互换或拆分（详见 §3、§5）。

### 0.4 机制与内容解耦（核心原则）

机制层只认识：`code`、`rarity`、`weight`、`discount_bp`、`is_active`、`is_limited`、`is_smeltable`、配方关系、券类型与数量。
展示层（名称、描述、图标、路线主题）放在内容表里，随时可替换。这样本稿可完全不含卡名，且未来扩池/换皮/改名不动抽卡与合成逻辑。

---

## 1. 设计目标

1. 给站内积分增加长期、可控的消耗入口：**用积分买券 → 用券抽卡**。
2. 给每日打卡增加轻量奖励：按名次档位发放抽卡券，让 51 名以后也能参与。
3. 用熔炼/合成消化重复与低档卡，避免"抽到重复就废"。
4. 用 UR 作为长期毕业目标，并附带 LDC 兑换折扣权益。
5. 完全复用现有积分钱包、流水、`write_txn()`、全局咨询锁和 `request_id` 幂等机制；**购券复用 LDC 商品的后台配置体系**。
6. 机制与卡名解耦：本稿可独立于内容侧定稿与实现。

非目标：不开放真实货币购买；不允许称号交易/赠送/兑换积分；券不可转让。

---

## 2. 卡池结构

### 2.1 数量与概率

| 稀有度 | 数量 | 池内总权重 | 单张概率 | 定位 |
|---|---:|---:|---:|---|
| N | 50 | 60% | 1.200% | 基础材料 |
| R | 30 | 28% | 0.933% | 普通中层 |
| SR | 20 | 9% | 0.450% | 路线进阶节点 |
| SSR | 7 | 3% | 0.429% | 路线核心、UR 材料 |
| UR | 4 | 0 | 合成限定 | 跨路线终点 |
| **合计** | **111** | **100%** | — | — |

- 每个稀有度内部**等权**；权重由后台维护，改动只影响未来抽取。
- 单张 SR 与单张 SSR 概率接近属正常：SR 有 20 张、SSR 只有 7 张，档位总量仍差 3 倍。
- UR 永不进入抽卡池，只能合成。
- 扩池按季度增加，只加 `title_defs` 行，不改表结构。

### 2.2 卡位字段（机制层）

- `code`：稳定唯一标识（如 `SSR-03`）。
- `rarity`：`N/R/SR/SSR/UR`。
- `weight`：同档内抽取权重，正整数。
- `discount_bp`：LDC 折扣，`10000`=无折扣、`9500`=95 折，合法区间 `9000–10000`。
- `is_active` / `is_limited` / `is_smeltable`：上架、限定、可熔炼；UR 必须 `is_smeltable=0`。
- 展示字段（名称/描述/图标/路线）放内容层，缺失时按占位剪影渲染，不影响抽卡。

---

## 3. 券式抽卡

### 3.1 抽卡只用券

- 抽卡接口**只消耗券**，不再使用积分直接抽卡。
- 每次请求指定一种券：`ticket_type ∈ {single, ten, hundred}`，对应一次抽 1 / 10 / 100。
- 三种券**各自整用**：单抽券只能抽 1 次、十连券只能一次抽 10、百连券只能一次抽 100；**不可拆分、不可混用**（不能"1 张十连券 + 2 张单抽券"凑 12 抽）。
- 同一批次内的所有抽，均计入保底与 `total_draws`。

### 3.2 不设抽卡上限

- **取消每日抽卡上限**，也**不设券持有上限**。抽多少只取决于手上券的数量。
- 防滥用不靠"游戏上限"，而靠：① 券必须用积分购买（有真实成本）；② 通用 API 限流/防刷（与现有访问风控一致）；③ 全量审计。
- 运营如需临时限流，使用网关级速率限制，不作为抽卡规则写进业务逻辑。

### 3.3 抽卡流程（服务端）

1. 校验登录、`ticket_type`、`request_id` 格式。
2. 按 `(user_id, request_id)` 查批次；存在且参数一致原样返回、不重复扣券；参数不一致 409。
3. 校验该用户对应券型余额 `>= 1`，不足返回 400（提示"该券不足，请先购买"）。
4. 读在售卡池，校验每个参与档位至少 1 个可用卡位；SSR 为空时禁用保底并后台告警。
5. 逐抽按权重产出；十连无 SR 及以上则末抽强制 SR，百连无 SSR 则末抽强制 SSR（§4.2）。
6. 首次获得插入 `user_titles`；重复则 `copies += 1`。
7. 扣该券型 1 张（写券流水，`reference=batch_id`）。
8. 更新 `pity/total_draws`，写批次与明细，提交。

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

### 4.2 保底（按券型，批次级）

- **十连券**：本次 10 抽若无 SR 及以上，则最后一抽强制 SR（若末抽本为 SSR 则保留 SSR，不降级）。
- **百连券**：本次 100 抽若无 SSR，则最后一抽强制 SSR。
- **单抽券**：无保底。
- **其他无保底**：不设跨批次累计保底、不设软保底、不设 80 抽硬保底；`pity` 恒为 0。
- 后台若无在售 SSR，百连保底自动禁用并在管理页告警；无 SR 则十连保底禁用。

### 4.3 概率口径

- 基础概率：N 60% / R 28% / SR 9% / SSR 3%。
- 十连保底使 SR 综合概率约 **11.8%**（公示值以实测为准）。
- 百连保底使「100 抽至少 1 个 SSR」成为确定事件。

### 4.4 随机数与公示

- 只用服务端 `secrets.randbelow`，不信任客户端传入的任何结果/种子。
- 单卡概率 = 该卡 `weight` / 同档总权重。
- `title_draws` 保存抽到时的稀有度快照；权重改动不影响历史。
- 公示口径：各档基础概率、单张概率、十连必出 SR、百连必出 SSR 的规则，页面可查。

---

## 5. 购券与送券

### 5.1 券的获取方式

| 来源 | 说明 |
|---|---|
| 积分购买 | 三种券作为后台商品配置，用积分按标价购买，即时到账 |
| 打卡送券 | 按名次档位发放，档位配置与积分独立（见 §5.4） |
| 管理员发放 | 后台手动发放/收回（二级密码） |

### 5.2 购券（复用 LDC 商品配置体系）

- 三种券在 `shop_products` 中以 **`category='TICKET'`** 建模，字段沿用 LDC 商品那套：`name / description / points_price / is_active`，另加 `draw_count ∈ {1,10,100}` 标识券面额。
- **价格后台设置**：每种券的 `points_price` 由管理员在后台配置，和 LDC 商品一样可改价、上下架。默认建议（示例，可改）：
  - 单抽券：50 分
  - 十连券：475 分（约 95 折）
  - 百连券：4500 分（约 9 折）
- **不限购**：不设单人/全站每日限购，仅受积分余额限制。
- 购买流程在单个 `write_txn()` 内完成（`shop_products` 不发外部货，无需两阶段）：
  1. 校验登录、`product_id`、`request_id`。
  2. 按 `(user_id, request_id)` 查 `shop_purchases`；已存在且商品一致则原样返回，否则 409。
  3. 读取商品，须为 `category='TICKET'` 且 `is_active=1`；取 `draw_count` 判定券型。
  4. 校验积分余额足够；`credits.spend_points(..., 'ticket_purchase', order_no, now)` 扣分并写积分流水。
  5. 对应券型余额 `+1`；写券流水 `title_ticket_ledger(ticket_type, delta=+1, reason='purchase', reference=order_no)`。
  6. 写 `shop_purchases`：`category='TICKET'`、`ldc_amount='0.00'`、`status='success'`、`draw_count` 快照，提交。
- 购券**不影响** LDC 每日兑换额度（`ldc_amount='0.00'`，且不计入 `daily_ldc_used`）。

### 5.3 券不可转让、不可回兑

- 券绑定账号，不可交易/赠送/回兑积分。
- 券无有效期（若要过期需另立规则，默认不过期）。

### 5.4 打卡送券（与积分独立的名次档位）

- 与现有积分 `reward_tiers` **同构、但独立**：在 `checkin_settings` 增加 `ticket_reward_tiers`，按累计名次上限 `through` 配置每个档位送的券面额与数量。
- 结构示例（**示例值，运营可改**）：

```json
[
  {"through": 10, "ticket_type": "ten",    "count": 1},
  {"through": 20, "ticket_type": "single", "count": 5},
  {"through": 50, "ticket_type": "single", "count": 2}
]
```

  - `through=10` 表示第 1–10 名；未命中的更高名次不再发券。
  - 同一档位可配置一种券；如需多种券，可拆成多条同 `through` 记录（实现上按 `through` 升序匹配，命中即取）。
- **在打卡完成、生成 `entries` 记录时发放**；51 名及以后是否发券由档位配置决定（不配即不发）。
- **待审核期间不发**，审核通过后按当天补发。
- **幂等**：`title_ticket_ledger` 用 `UNIQUE(user_id, ticket_type, reason, reference)`，`reference='checkin:{day}'`，同一用户同一天同一种券只发一次。
- 不再固定"1 张/天 + 连签 3/7 天加成"；连签额外券如需保留，作为独立的额外档位/规则配置，默认不加。

---

## 6. 熔炼与合成

### 6.1 比例

| 操作 | 随机 | 定向 |
|---|---:|---:|
| N → R | 3 张 N | 6 张 N |
| R → SR | 3 张 R | 6 张 R |
| SR → SSR | 5 张 SR | 10 张 SR |
| UR | — | 3 张指定 SSR（消耗）→ 1 张 UR |

等价关系（不计随机与重复）：
- **45 张 N = 1 张随机 SSR**（3 × 3 × 5）
- **360 张 N = 1 张指定 SSR**（6 × 6 × 10）

### 6.2 材料规则

- 熔炼材料必须是**同一稀有度**的副本；UR 合成材料必须与配方完全一致。
- 熔炼不要求同名；UR 合成固定消耗 3 种不同指定 SSR，各 1 张。
- 材料由用户显式勾选；服务端校验数量、稀有度、副本数与装备状态，不能静默自动消耗最后一张。
- 熔炼与合成都不可逆；界面必须显示"将消耗哪些卡、哪些会从图鉴消失"，并二次确认。
- 随机熔炼优先产出未拥有的目标；该档全部拥有时给随机重复副本。
- 定向熔炼可选任意同档下一等级的在售卡位；已拥有则变副本，界面需提示。
- 结果、消耗材料、时间写入 `title_crafts`，用于审计和幂等。

### 6.3 最后一张与装备

- **未装备**的卡可以熔炼/合成到最后一张，甚至 0 张；到 0 时删除 `user_titles` 行，从图鉴移除，重新抽到才算再次拥有。
- **装备中**的卡至少保留 1 张：`可消耗数量 = copies - (已装备 ? 1 : 0)`。
- 装备中的重复副本可作材料，不能消耗装备本体；要用最后一张须先卸下。
- UR 不可熔炼。
- SSR 被合成消耗后，依赖它的 UR 配方按剩余副本数重新显示缺口。

### 6.4 UR 配方（槽位引用，不含卡名）

首发 4 个 UR、7 个 SSR，每个 UR 固定消耗 3 种不同指定 SSR 各 1 张。同一 SSR 可参与多个配方，但每次合成都需再次提供副本。

| UR | 消耗的 3 个 SSR 卡位 |
|---|---|
| UR-01 | SSR-01 + SSR-02 + SSR-07 |
| UR-02 | SSR-01 + SSR-03 + SSR-04 |
| UR-03 | SSR-04 + SSR-05 + SSR-06 |
| UR-04 | SSR-02 + SSR-03 + SSR-05 |

4 个 UR 的累计材料需求：

| SSR 卡位 | 总需求 | 用于 UR |
|---|---:|---|
| SSR-01 | 2 | UR-01、UR-02 |
| SSR-02 | 2 | UR-01、UR-04 |
| SSR-03 | 2 | UR-02、UR-04 |
| SSR-04 | 2 | UR-02、UR-03 |
| SSR-05 | 2 | UR-03、UR-04 |
| SSR-06 | 1 | UR-03 |
| SSR-07 | 1 | UR-01 |

- 做完 4 个 UR 共消耗 12 张 SSR（5 种共享各 2 张、2 种独特各 1 张），不是"集齐 7 种后永久解锁"。
- 每个 UR 账号唯一；已拥有该 UR 时再合成返回 409，且不得扣材料。
- UR 合成后不自动装备，由用户自选。
- 配方是配置项（`title_config`），换配方不改代码；上线前须校验每个 SSR 至少进入 1 个配方、每个配方 3 张不同 SSR。

### 6.5 结果与审计

- `title_crafts.materials` 保存 `[{title_id, count}]` 快照。
- 同一 `request_id` 重试返回原结果，不重复消耗。
- 随机/定向/UR 三类共用 `title_crafts`，用 `kind` 区分。

---

## 7. UR 权益（LDC 折扣）

### 7.1 范围

- 只影响商店 `category='LDC'` 的**积分价格**，不影响 LDC 到账数量。
- 不影响赞助、打卡奖励、抽卡、券价格。
- 4 个 UR 默认都配 `discount_bp=9500`；多个折扣卡位不叠加，取最优折扣。
- 折扣**拥有即生效**，不要求装备；装备只影响展示。

### 7.2 计算

```text
实付积分 = ceil(原积分价 × discount_bp / 10000)
500 分 × 9500 / 10000 = 475 分
333 分 × 9500 / 10000 = 317 分（向上取整）
```

### 7.3 每日节省上限

- 默认 `DAILY_DISCOUNT_SAVE_CAP=500` 积分/人/天，由后台或环境变量配置。
- 接近上限时按剩余额度**部分打折**；达到上限后本日后续 LDC 兑换按原价。
- `failed` 订单不计入已省额度；退款/对账失败后额度释放。
- 只统计 `pending/success/simulated/uncertain` 状态，与 LDC 每日额度口径一致。

### 7.4 订单审计字段

`shop_purchases` 增加：

| 字段 | 含义 |
|---|---|
| `points_cost_original` | 折扣前积分价 |
| `points_discount_bp` | 本单使用的折扣（10000 / 9500） |
| `points_discount_saved` | 本单实际节省积分 |
| `points_cost` | 实际支付积分（保持原字段） |

- 退款按 `points_cost`（实付）退，不按原价退。
- 管理后台增加"今日折扣总节省""UR 持有人数"统计。
- 折扣计算在 `_reserve` 事务内完成，服务端读已拥有卡位，不信任前端。

---

## 8. 经济与节奏

### 8.1 抽数价值

- 积分抽卡的唯一路径是"买券"；每抽成本由券价决定，百连最便宜。
- 以示例默认价：单抽 50/抽、十连 47.5/抽、百连 45/抽。
- 1000 积分可购：20 张单抽券（20 抽）、或 2 张十连券（20 抽）+ 余 50 分再单抽 = 21 抽、或约 1/4.5 张百连券。

### 8.2 期望出货

20 抽（从 0 保底开始）：

| 稀有度 | 期望个数 | 至少 1 个的概率 |
|---|---:|---:|
| N | 12.0 | 约 100% |
| R | 5.6 | 99.9% |
| SR | 1.8 | 84.8% |
| SSR | 0.6 | 45.6% |

- 约 54.4% 的 20 抽批次没有 SSR；约 15.2% 没有 SR。
- 若已有 60+ 保底进度，会触发 SSR，实际更好。

### 8.3 目标路径（概率期望，非保底承诺）

| 目标 | 路径 | 约抽数 | 约积分（按 47.5/抽） |
|---|---|---:|---:|
| 第一张 UR | 获得任一配方的 3 种 SSR 并消耗 | 约 205 | 约 9,750 |
| 4 张 UR | 满足 `2+2+2+2+2+1+1` 的指定 SSR 需求 | 约 830 | 约 39,400 |
| 全图鉴（不含 UR） | 不熔炼 | 882 | 约 41,900 |

- 定向熔炼会显著缩短缺特定材料的时间；实际受 SSR 重复分布影响。

### 8.4 1000 分的产出（约 21 抽）

- 直接抽：约 12.6 N / 5.9 R / 1.9 SR / 0.6 SSR。
- 全熔炼（N→R 3、R→SR 3、SR→SSR 5）：约 **1.7 SSR**。
- 全熔炼会失去大量 N/R/SR 图鉴，适合冲 UR 的玩家。

---

## 9. 数据模型

所有表使用雪花 ID、`DOUBLE PRECISION` 时间戳，沿用现有 `sql/schema.sql` 幂等风格。以下为机制必需结构。

### 9.1 `title_defs`（机制层卡位）

```sql
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
```

### 9.2 `title_content`（展示层，可替换）

```sql
CREATE TABLE IF NOT EXISTS title_content (
    title_id      BIGINT PRIMARY KEY REFERENCES title_defs(id),
    name          TEXT NOT NULL DEFAULT '',
    description   TEXT NOT NULL DEFAULT '',
    icon          TEXT NOT NULL DEFAULT '',
    route         TEXT NOT NULL DEFAULT '',
    source_type   TEXT NOT NULL DEFAULT 'generated' CHECK (source_type IN ('badge','generated')),
    updated_at    DOUBLE PRECISION NOT NULL
);
```

- 名称/描述按纯文本渲染，禁止 HTML。内容缺失时按占位剪影处理。

### 9.3 `user_titles`

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

### 9.4 `user_title_state`（含三种券余额）

```sql
CREATE TABLE IF NOT EXISTS user_title_state (
    user_id            TEXT PRIMARY KEY,
    equipped_title_id  BIGINT REFERENCES title_defs(id),
    tickets_single     INTEGER NOT NULL DEFAULT 0 CHECK (tickets_single >= 0),
    tickets_ten        INTEGER NOT NULL DEFAULT 0 CHECK (tickets_ten >= 0),
    tickets_hundred    INTEGER NOT NULL DEFAULT 0 CHECK (tickets_hundred >= 0),
    pity               INTEGER NOT NULL DEFAULT 0 CHECK (pity >= 0),
    total_draws        BIGINT NOT NULL DEFAULT 0
);
```

> 券余额按面额分列存储，读取快；如需扩展面额可改独立的 `title_ticket_balances(user_id, ticket_type, balance)` 表，本稿默认三列。

### 9.5 `title_draw_batches`

```sql
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
```

### 9.6 `title_draws`

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

### 9.7 `title_crafts`

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

### 9.8 `title_ticket_ledger`（按券型分账）

```sql
CREATE TABLE IF NOT EXISTS title_ticket_ledger (
    id            BIGINT PRIMARY KEY,
    user_id       TEXT NOT NULL,
    ticket_type   TEXT NOT NULL CHECK (ticket_type IN ('single','ten','hundred')),
    delta         INTEGER NOT NULL,
    reason        TEXT NOT NULL,          -- 'purchase' / 'checkin' / 'admin'
    reference     TEXT NOT NULL,
    balance_after INTEGER NOT NULL,
    created_at    DOUBLE PRECISION NOT NULL,
    UNIQUE (user_id, ticket_type, reason, reference)
);
CREATE INDEX IF NOT EXISTS title_ticket_ledger_user ON title_ticket_ledger(user_id, id DESC);
```

### 9.9 `title_config`

```sql
CREATE TABLE IF NOT EXISTS title_config (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
```

保存：熔炼/合成成本、UR 配方、每日折扣上限等。**不再保存每日抽卡上限与保底参数**（保底按券型固定：十连 SR、百连 SSR）。

> 签到送券档位不放这里，放在 `checkin_settings.ticket_reward_tiers`（与积分 `reward_tiers` 同级、独立配置）。

### 9.10 商店表调整（复用 LDC 商品体系）

```sql
-- 券商品：category='TICKET'，draw_count 标识面额
ALTER TABLE shop_products ADD COLUMN IF NOT EXISTS draw_count INTEGER NOT NULL DEFAULT 0;

-- 订单快照：券订单 draw_count
ALTER TABLE shop_purchases ADD COLUMN IF NOT EXISTS draw_count INTEGER NOT NULL DEFAULT 0;
ALTER TABLE shop_purchases ADD COLUMN IF NOT EXISTS points_cost_original BIGINT;
ALTER TABLE shop_purchases ADD COLUMN IF NOT EXISTS points_discount_bp INTEGER NOT NULL DEFAULT 10000;
ALTER TABLE shop_purchases ADD COLUMN IF NOT EXISTS points_discount_saved BIGINT NOT NULL DEFAULT 0;
```

- 券订单：`category='TICKET'`、`ldc_amount='0.00'`、`status='success'`、`draw_count` 快照；不计入 LDC 每日额度。
- 历史订单展示原价用 `COALESCE(points_cost_original, points_cost)`，退款按 `points_cost`（实付）。

### 9.11 积分流水

- 购券：`points_ledger.kind='ticket_purchase'`，`reference=order_no`，`UNIQUE(kind, reference)` 提供幂等。
- 抽卡：不写积分流水（只扣券）。
- 熔炼/合成：不写积分流水。
- 称号不能卖，无 `title_sale` 流水。

### 9.12 测试表清理

`tests/conftest.py` 的 `TABLES` 需加入：

```text
title_defs, title_content, user_titles, user_title_state,
title_draw_batches, title_draws, title_crafts, title_ticket_ledger, title_config
```

（`shop_products` / `shop_purchases` 已在既有测试表内，扩展列后继续复用。）

---

## 10. API

与商店一致：配置 OAuth 后，个人数据接口要求登录；访客可看卡池与概率，但不能抽卡/购券。

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/titles` | 卡池、图鉴、装备、三种券余额、券商品与价格、保底、配方、抽卡记录 |
| POST | `/api/titles/draw` | 抽卡：`{ticket_type, request_id}`，`ticket_type ∈ single/ten/hundred` |
| POST | `/api/titles/tickets/purchase` | 购券：`{product_id, request_id}`，用积分购买 |
| POST | `/api/titles/equip` | 装备/卸下，`title_id` 或 `null` |
| POST | `/api/titles/smelt` | 熔炼：`mode=random/target`、`input_rarity`、`target_title_id`、`materials`、`request_id` |
| POST | `/api/titles/craft` | UR 合成：`{recipe_id, materials, request_id}` |
| GET | `/api/titles/history` | 最近抽卡、熔炼、合成、购券记录 |
| GET | `/api/shop` | 增加当前折扣、今日已省、剩余额度 |
| POST | `/api/shop/purchase` | 服务端自动应用折扣并写审计字段 |
| GET | `/api/admin/titles` | 管理后台卡位列表 |
| POST | `/api/admin/titles` | 新建/修改卡位、权重、折扣、可熔炼 |
| POST | `/api/admin/titles/grant` | 手动发放/收回卡位或券（二级密码） |
| GET | `/api/admin/title-stats` | 抽卡、购券、送券、熔炼、UR、折扣统计 |

> 券商品的新增/改价/上下架直接复用现有后台 **商品管理**（`POST /api/admin/products`），只需接受 `category='TICKET'` 与 `draw_count`。

### 10.1 抽卡请求/响应

请求：

```json
{ "ticket_type": "ten", "request_id": "..." }
```

响应（不含卡名，`title_id` 由前端映射内容）：

```json
{
  "batch": { "id": "123", "ticket_type": "ten", "count": 10 },
  "results": [ { "title_id": "456", "rarity": "SR", "is_new": true } ],
  "pity": 12,
  "pity_limit": 80,
  "tickets": { "single": 3, "ten": 4, "hundred": 0 }
}
```

### 10.2 购券请求/响应

请求：

```json
{ "product_id": "9001", "request_id": "..." }
```

响应：

```json
{
  "order": { "order_no": "SO-20261123-ABCDEF", "category": "TICKET", "points_cost": 475, "draw_count": 10 },
  "status": "success",
  "ticket_type": "ten",
  "tickets": { "single": 3, "ten": 5, "hundred": 0 },
  "wallet": { "balance": 525 }
}
```

### 10.3 熔炼/合成响应（示例）

```json
{
  "kind": "smelt_random",
  "output": { "title_id": "789", "rarity": "SR", "is_new": true },
  "consumed": [ { "title_id": "1", "count": 3 } ],
  "collection": { "copies": 0 }
}
```

---

## 11. 事务、并发与幂等

所有写操作在 `app/infrastructure/database.write_txn()` 内完成；现有全局 `pg_advisory_xact_lock` 串行化关键写流程。

### 11.1 抽卡

1. 校验登录、`ticket_type`、`request_id` 格式。
2. 按 `(user_id, request_id)` 查 `title_draw_batches`；存在且参数一致原样返回、不重复扣券；参数不一致 409。
3. 校验对应券型余额 `>= 1`，不足 400。
4. 读在售卡池，校验档位可用；SSR 为空时禁用保底并告警。
5. 逐抽按 §4 计算；每 10 抽区块应用 SR 保底；记录 `pity_before`。
6. 首次获得插入/更新 `user_titles`；重复 `copies += 1`。
7. 扣该券型 1 张，写 `title_ticket_ledger(delta=-1, reason='draw', reference=batch_id)`。
8. 更新 `pity/total_draws`，插入批次与明细，提交。

### 11.2 购券

1. 校验登录、`product_id`、`request_id` 格式。
2. 按 `(user_id, request_id)` 查 `shop_purchases`；存在且 `product_id` 一致返回原单，否则 409。
3. 读商品：须 `category='TICKET'` 且 `is_active=1`，`draw_count ∈ {1,10,100}`。
4. 校验积分余额；`credits.spend_points(user, points_price, 'ticket_purchase', order_no, now)`。
5. 对应券型 `+1`，写 `title_ticket_ledger(delta=+1, reason='purchase', reference=order_no)`。
6. 写 `shop_purchases`（TICKET / ldc_amount 0 / success / draw_count 快照），提交。
7. 幂等：同 `(user_id, request_id)` 并发只生效一次；不产生负余额。

### 11.3 熔炼/合成

1. 校验登录、`request_id`、材料格式。
2. 按 `(user_id, request_id)` 查 `title_crafts`；存在且参数一致返回原结果，参数不一致 409。
3. 校验同稀有度、数量等于配方、`copies` 足够、未被装备到 0。
4. 消耗副本；`copies=0` 删除 `user_titles` 行。
5. 随机/定向选出产出；插入或增加 `user_titles`。
6. 写 `title_crafts`（含 `materials` 快照），提交。
7. UR 合成额外校验：已拥有该 UR 则 409；3 张指定 SSR 副本足够。

### 11.4 打卡送券

1. 打卡完成事务内，确认该用户有当天 `entries` 记录且非待审核。
2. 按当前名次匹配 `ticket_reward_tiers`（`rank <= through` 的最小档）。
3. 校验积分档位与券档位互不影响（两套配置分开）。
4. 写 `title_ticket_ledger(ticket_type, delta=+count, reason='checkin', reference='checkin:{day}')`，唯一约束防重复。
5. 更新 `user_title_state` 对应券余额。
6. 待审核不发放；审核通过后按当天补发（同样幂等）。

### 11.5 装备

- 装备前确认 `user_titles.copies >= 1`；否则 409。
- 装备中的卡至少保留 1 张；所有熔炼/合成材料校验都要读当前装备。
- 卸下允许；卸下后最后一张可被熔炼。

---

## 12. 前端

### 12.1 `/titles` 页面

- 顶部：积分余额、三种券余额（单抽/十连/百连各显示数量）、保底规则提示（十连 SR、百连 SSR、单抽无保底）。
- 抽卡区：三个按钮 **单抽 / 十连 / 百连**，各自显示"持有 X 张"；券不足时按钮显示"去购买"并跳购券区。
- 购券区：三个券商品卡片，显示后台配置的积分价与"购买"按钮；购券后即时刷新券余额；显示积分余额与不足提示。
- 概率公示与保底说明（十连必出 SR、百连必出 SSR、单抽无保底）。
- 图鉴区：按稀有度分组，显示已拥有/副本数/装备状态；未拥有显示剪影。
- 熔炼/合成区：按稀有度显示可用副本，显式勾选；显示配方、产出预览、将失去的图鉴警告；UR 配方显示 4 个 UR 的材料清单，红/绿标识缺口。
- 记录区：最近 50 次抽卡、购券、熔炼、合成。
- 空状态/未登录：展示卡池、概率与券价，抽卡/购券按钮提示登录。

### 12.2 打卡页

- 完成打卡后按档位显示"获得 X 张【十连券】"等；不命中档位则不显示。
- 展示当前名次与对应券档位（与积分类似并列展示，但数据源独立）。

### 12.3 商店

- 有折扣时显示横幅："UR 权益生效：LDC 兑换 95 折，今日还可省 X 积分"。
- 商品卡片显示原价、实付价、本单节省；达到上限显示"今日折扣额度已用完"。
- 无折扣时提示"拥有 UR 可享 LDC 兑换 95 折"。

### 12.4 榜单

- 打卡榜、训练榜用户名旁显示装备称号标签；UR 使用专属样式；未装备不显示。

### 12.5 导航与路由

- 新增 `/titles` 路由，导航「称号」放在「商店」之后。
- 更新 `SiteNavigation.vue`、`router/index.ts`、`api/index.ts` 类型。

---

## 13. 管理后台

新增「称号管理」：

- **券商品管理**：复用现有商品管理，支持 `category='TICKET'` + `draw_count(1/10/100)` + `points_price` + 上/下架；改价即时生效；校验 `draw_count` 只能是 1/10/100、价格 0–1 亿整数。
- **卡位 CRUD**：稀有度、权重、`discount_bp`、上架/下架、限定、可熔炼；名称/描述/图标在内容区维护。
- **签到送券档位**：`ticket_reward_tiers` 编辑器，与积分 `reward_tiers` 并列但独立；支持增删档位、选券面额与数量；校验 `through` 递增、`count >= 1`、`ticket_type` 合法。
- **配方配置**：熔炼随机/定向成本、UR 配方、每日折扣上限。
- **统计**：抽卡次数（按券型）、购券消耗积分、送券数量、各档出货、SSR/UR 数量、UR 持有人数、每日折扣总节省。
- **手动发放/收回**：卡位或券（二级密码）。
- **校验**：
  - 权重为正整数；每个在售档位至少 1 个卡位。
  - 保底启用时必须有在售 SSR。
  - UR 必须 `is_smeltable=0`，配方材料存在、每个 SSR 至少进 1 个配方。
  - `discount_bp` 在 9000–10000；多折扣卡位不叠加，提示当前最优折扣。
  - 修改权重/折扣只影响未来，历史 `title_draws`/`title_crafts` 保留快照。

---

## 14. 风控与合规

- **不可出售/交易/赠送/兑换积分**：称号是账号绑定资产；券也不可转让/回兑。
- **概率公示**：展示各档基础概率、单张概率、十连必出 SR、百连必出 SSR 的规则。
- **不开放充值抽卡**：券只能用站内积分购买，积分只能来自打卡/排名奖励/管理员发放；不提供真实货币购买。
- **无抽卡上限的补偿控制**：靠"券有真实积分成本 + 网关限流 + 全量审计"防滥用，不设游戏内每日上限。
- **审计**：所有抽卡、购券、送券、熔炼、合成留记录；管理员只能查看历史，不能改历史。
- **防小号**：打卡送券要求完成打卡；称号/券绑定不可转移，开小号收益有限；仍按账号限流。
- **XSS**：名称/描述按纯文本渲染，禁止 HTML。
- **经济监控**：每日购券消耗积分、送券数量、各券型库存、SSR/UR 数量、LDC 折扣节省、LDC 兑换量；异常时先调券价/送券档位，再改权重。

---

## 15. 测试

至少覆盖：

1. 购券：积分扣减正确、余额不足拒绝、`request_id` 幂等、券即时到账、`draw_count` 与券型一致；购券不影响 LDC 每日额度。
2. 抽卡只用券：单抽/十连/百连分别扣对应券型各 1 张；无对应券时 400；**不可拆分/混用**；无每日抽卡上限（连续多批均成功）。
3. 保底：十连无 SR 及以上则末抽强制 SR；百连无 SSR 则末抽强制 SSR；单抽无保底。
4. 百连保底：100 抽无 SSR 时末抽强制 SSR；末抽本为 SSR 不降级。
5. 图鉴/副本：首次 `is_new=1`，重复 `copies+1`。
6. 熔炼：随机/定向、同稀有度校验、数量校验、最后一张可熔炼、装备中至少留 1、熔炼到 0 删除。
7. UR：3 张指定 SSR 消耗、已拥有拒绝、材料不足拒绝、共享配方正确、4 个 UR 共需 12 张 SSR。
8. 打卡送券：按 `ticket_reward_tiers` 发放；与积分档位互不影响；`checkin:{day}` 幂等；待审核不发、通过后补发；51+ 按配置决定。
9. 折扣：UR 95 折、非 UR 原价、多 UR 不叠加、每日节省上限、部分折扣、退款释放额度、只影响 LDC。
10. 商店退款：按实付积分退，不按原价退。
11. 榜单：装备称号显示、未装备不显示、UR 样式。
12. 后台：券商品 `draw_count`/价格校验、送券档位校验、权重/折扣/配方校验、手动发放/收回、统计。
13. 并发：相同 `request_id` 并发只生效一次；抽卡不出现负券；购券不出现负积分。
14. 内容解耦：`title_content` 缺失名称时抽卡/熔炼仍成功，前端按剪影展示。

---

## 16. 实施顺序

1. `sql/schema.sql` 新表 + `shop_products/shop_purchases` 扩列 + `app/service/titles.py` + 券/抽卡/保底/送券/熔炼/UR/折扣测试。
2. 后台商品管理支持 `TICKET` + `draw_count` + 改价。
3. `/api/titles`、`/api/titles/draw`、`/api/titles/tickets/purchase` + `/titles` 页面 + 导航/路由/类型。
4. 打卡完成按档位送券 + 打卡页展示。
5. 商店折扣接入 + `shop_purchases` 审计字段 + 商店 UI。
6. 装备展示 + 打卡榜/训练榜联表。
7. 管理后台称号管理 + 送券档位 + 统计。
8. 内容表接入：把《称号内容表》灌入 `title_content`，本稿机制不改。
9. 上线后观察 2–4 周，调整券价、送券档位、UR 配方和折扣上限。

---

## 17. 与旧稿（title_gacha.md）的主要差异

| 维度 | 旧稿 | 本稿 v2.1 |
|---|---|---|
| 卡名 | 正文含大量具体称号名 | 全文不含卡名，机制与内容解耦 |
| 抽卡货币 | 50 分/抽或券，积分可直接抽 | **只用券**；积分只能买券 |
| 券形态 | 单一抽卡券 | **单抽/十连/百连三种独立面额，各自整用** |
| 购券 | 无 | 复用 LDC 商品体系，后台设价，不限购 |
| 抽卡上限 | 每日 50 抽 | **取消** |
| 券上限 | 持有 20 张 | **取消** |
| 打卡送券 | 固定 1 张/天 + 连签加成 | **名次档位配置，与积分独立** |
| 存档结构 | `title_defs` 内含名称 | 拆出 `title_content` 展示层 |
| 保底 | 仅 80 抽硬保底 | 十连必出 SR、百连必出 SSR、单抽无保底 |
| 十连 SR 保底 | 默认关闭 | 默认开启并公示综合概率 |
| UR 配方 | 用称号名描述 | 用 SSR 槽位引用，换名不改逻辑 |
| 抽卡响应 | 含 `name` | 只回 `title_id`，文案由前端拼装 |

---

## 18. 待确认 / 可配置

| 项 | 默认 | 备选 |
|---|---|---|
| 券价（积分） | 单抽 50 / 十连 475 / 百连 4500 | 后台任意改价 |
| 二十连/更多面额 | 仅三档 | 可扩至更多 `draw_count` |
| 十连保底 | 必出 SR 及以上 | 关闭 |
| 百连保底 | 必出 SSR | 关闭 |
| 打卡送券档位 | 见 §5.4 示例 | 后台任意增删改 |
| 4 个 UR 的 95 折 | 4 个都有 | 只有 1 个有，其余纯外观 |
| UR 配方 | 3 张指定 SSR 消耗 | 调整配方 |
| 卡池权重 | N60/R28/SR9/SSR3 | 后台可调 |

---

## 19. 验收标准

- 用户可用积分购买三种券，券即时到账；购券幂等、不产生负积分。
- 三种券只能用于对应抽数（单抽/十连/百连），不可拆分或混用；无对应券时明确提示购买。
- 不设每日抽卡上限与券持有上限，连续大批量抽卡均正常。
- 抽卡扣券、副本、图鉴、记录正确；十连必出 SR、百连必出 SSR、单抽无保底。
- 打卡按 `ticket_reward_tiers` 发券，与积分档位独立；重复请求不重复发；待审核不发、通过后补发。
- 未装备卡位可熔炼到最后一张并移出图鉴；装备中至少保留 1 张。
- 4 个 UR 可按共享配方合成；材料不足/已拥有时有明确错误。
- UR 拥有者兑换 LDC 自动 95 折，受每日节省上限约束；退款按实付积分退。
- 打卡榜/训练榜显示装备称号；管理后台可维护券商品、送券档位、卡位、权重、折扣、配方和统计。
- 概率、保底、券价、送券规则页面可查；所有写操作有幂等与审计记录。
- **机制层完全不依赖卡名**：替换《称号内容表》后，购券、抽卡、熔炼、合成、折扣、统计行为不变。

# 提肛打卡与积分商城 · 前端视觉与交互重构需求规格书 (PRD & Design Spec)

> **版本**：v1.0.0  
> **面向对象**：UI 设计师 / AI 绘图模型 (GPT-4o / Midjourney) / 前端开发  
> **核心基调**：告别粗糙简陋的“小圆卡片堆砌感”，全面演进为 **现代、精致、大气质感、零布局跳动** 的高品质 Web 应用（对标 **Linear.app / Vercel / Raycast / Apple Developer** 极简科技风格）。

---

## 目录
- [一、 重构背景与三大核心痛点治理](#一-重构背景与三大核心痛点治理)
  - [1. 痛点一：向下滑动时标题/导航滑走，缺乏吸顶常驻](#1-痛点一向下滑动时标题导航滑走缺乏吸顶常驻)
  - [2. 痛点二：满屏孤立臃肿的“小圆卡片”风格过时且简陋](#2-痛点二满屏孤立臃肿的小圆卡片风格过时且简陋)
  - [3. 痛点三：点击或异步操作导致页面宽度/结构跳动 (Layout Shift)](#3-痛点三点击或异步操作导致页面宽度结构跳动-layout-shift)
- [二、 现代视觉设计系统规范 (Design System Tokens)](#二-现代视觉设计系统规范-design-system-tokens)
  - [1. 色彩与表面层级 (Surfaces & Colors)](#1-色彩与表面层级-surfaces--colors)
  - [2. 圆角与边框系统 (Borders & Radius)](#2-圆角与边框系统-borders--radius)
  - [3. 排版与等宽数字 (Typography)](#3-排版与等宽数字-typography)
- [三、 各核心页面交互与布局重构规格](#三-各核心页面交互与布局重构规格)
  - [1. 全局导航栏 (Global Sticky Header)](#1-全局导航栏-global-sticky-header)
  - [2. 商店与积分中心 (Shop Page) —— 重点重构](#2-商店与积分中心-shop-page--重点重构)
  - [3. 首页打卡与今日领奖台 (Home Page)](#3-首页打卡与今日领奖台-home-page)
  - [4. 称号与抽卡中心 (Titles Page)](#4-称号与抽卡中心-titles-page)
  - [5. 提肛练习 (Practice) 与 赞助 (Donate) / 管理后台 (Admin)](#5-提肛练习-practice-与-赞助-donate--管理后台-admin)
- [四、 直接提供给 GPT / Midjourney 的出图提示词 (AI Prompt)](#四-直接提供给-gpt--midjourney-的出图提示词-ai-prompt)
  - [Prompt 1：商店与积分中心 (Desktop 1440px 主视图)](#prompt-1商店与积分中心-desktop-1440px-主视图)
  - [Prompt 2：首页打卡与灵动呼吸环 (Interactive Stage)](#prompt-2首页打卡与灵动呼吸环-interactive-stage)
  - [Prompt 3：称号抽取与 3D 翻牌展览室 (Gacha & Badges)](#prompt-3称号抽取与-3d-翻牌展览室-gacha--badges)
- [五、 技术实现要求与验收标准 (Checklist)](#五-技术实现要求与验收标准-checklist)

---

## 一、 重构背景与三大核心痛点治理

### 1. 痛点一：向下滑动时标题/导航滑走，缺乏吸顶常驻
* **现状分析**：
  * 当前页面向下滚动时，全局 Header 随着滚走，或者在页面有内嵌长列表时用户完全丧失上下文信息；
  * 在长页面（如商店发货记录、积分明细、称号图鉴）中，用户滚动到中后段时无法一眼看清自己的当前余额、无法随时切页，体验非常割裂。
* **重构规范**：
  1. **全局主导航栏（Global Header）强力吸顶**：
     * 保持 `position: sticky; top: 0; z-index: 100`，同时设置 `backdrop-filter: blur(20px)`，半透明背景（75%~85% 表面透明度），滚动时背景内容自如在下方穿透；
     * 移除破坏 sticky 的父级 overflow 约束，确保全视口各端均稳定吸顶。
  2. **局部次级吸顶条（Sticky Subheader / Asset Bar）**：
     * **商店页**：页面下滑离开 Hero 区后，顶部的「可用积分余额 + UR折扣状态 + 全站LDC额度池」自动过渡固定在全局导航栏下方，高度约 48px，方便长距离翻阅商品与记录时随时核对资产；
     * **称号页**：滚动图鉴列表时，「单抽券 / 十连券 / 百连券余量 + 已装配称号」固定在次级吸顶条上。

---

### 2. 痛点二：满屏孤立臃肿的“小圆卡片”风格过时且简陋
* **现状分析**：
  * 目前每个组件都被一个独立的纯白小盒子包裹，使用粗大的圆角（`18px ~ 24px`）和生硬的四周阴影，大量堆砌导致页面呈现“零碎塑料积木感”；
  * 各信息块之间缺乏内在韵律与主次梯次，没有高级 SaaS 产品的现代开阔感。
* **重构规范（Modern Bento Grid & Border-First UI）**：
  1. **放弃粗笨大圆角**：
     * 主板块外框统一收敛至 **12px**；
     * 内部单元格/次级卡片统一使用 **8px ~ 10px**；
     * 徽章 Badge 采用 **4px ~ 6px** 的微圆角或标准 Pill 胶囊，告别笨钝感。
  2. **边框优先（Border-First）代替厚重阴影**：
     * 采用 **1px 极细微半透明边框**（如浅色下 `border: 1px solid rgba(226, 232, 240, 0.8)`，暗色下 `border: 1px solid rgba(255, 255, 255, 0.08)`）；
     * 辅以极其微弱的弥散环境光阴影，消除脏乱的黑灰色投影块。
  3. **整体平铺 Bento 布局**：
     * 将原来散落的卡片整合成富有逻辑的仪表盘网格（Bento Box），通过底色微妙明度差（Canvas `#f8fafc` 与 Surface `#ffffff`）划分功能区，视觉整体统一。

---

### 3. 痛点三：点击或异步操作导致页面宽度/结构跳动 (Layout Shift)
* **现状分析**：
  * **滚动条导致横向跳动**：切换选项卡（如商店“兑换发货记录”与“积分明细”切换）、展开折叠内容时，页面高度从“无滚动条”变为“有滚动条”，整个页面所有居中元素瞬间往左平移 15px 左右，视觉体验极度不适；
  * **异步按钮与文本变化撑破容器**：按钮文案从“立即兑换”变为“兑换中…”或“已抢光”，因字体变长把整行卡片或周边元素顶开错位；
  * **打卡呼吸环切换到领奖台高度断层**：不同视图的高度跳变导致下方内容大幅度上下抽搐；
  * **原生 `<dialog>` 弹窗唤醒**：原生弹窗打开时浏览器强制隐藏滚动条引发整体布局横跳。
* **重构规范（Zero Layout Shift 准则）**：
  1. **全局预留滚动条轨道**：
     * 全局样式必须引入：`html { scrollbar-gutter: stable both-edges; }` 或 `overflow-y: scroll;`，杜绝任何滚动条引发的页面左右抖动。
  2. **交互容器尺寸锁死**：
     * 所有异步操作按钮（兑换、抽卡、打卡）显式设定 `min-width`，使用 Flex 居中，文案变更不改变按钮物理尺寸；
     * 所有 Grid 与 Flex 子项必须带有 `min-width: 0` 防溢出规则。
  3. **视图切换高度骨架化与淡入淡出 (Cross-fade)**：
     * 首页核心打卡操作区设定固定最小高度（`min-height: 480px`），呼吸环完成打卡后，通过平滑的 `opacity` 淡入淡出过渡到今日领奖台，下方榜单位置稳如磐石。
  4. **优雅的 Drawer 抽屉或防抖 Modal**：
     * 弹窗展开时禁止动态修改 body 的 `overflow` 宽度，保持页面主体宽度百分之百不变。

---

## 二、 现代视觉设计系统规范 (Design System Tokens)

### 1. 色彩与表面层级 (Surfaces & Colors)
| Token 类别 | 浅色模式 (Light) | 深色模式 (Dark) | 描述 / 使用场景 |
| :--- | :--- | :--- | :--- |
| **Canvas** (主画布背景) | `#f8fafc` (Slate-50) | `#090d16` (Deep Charcoal) | 页面最底层底色，配以极轻微的微光暗纹 |
| **Surface-1** (主面板) | `#ffffff` (Pure White) | `#111827` (Gray-900) | Bento 网格基础面板、主要表格容器 |
| **Surface-2** (次级卡片) | `#f1f5f9` (Slate-100) | `#1a2234` (Surface-Elevated) | 内部微卡片、输入框背景、代码块底色 |
| **Primary** (核心品牌主色) | `#0d9488` (Teal-600) | `#14b8a6` (Teal-500) | 核心操作按钮、选中态、进度环高光 |
| **Accent Gold** (特权与UR) | `#f59e0b` (Amber-500) | `#fbbf24` (Amber-400) | UR 95折徽章、至尊称号光晕、排行榜前三 |
| **Emerald** (成功与到账) | `#10b981` (Emerald-500) | `#34d399` (Emerald-400) | 自动发货成功、积分入账、签到成功 |
| **Text Main** (主文字) | `#0f172a` (Slate-900) | `#f8fafc` (Slate-50) | 一级标题、关键资产数值 |
| **Text Muted** (次级文字) | `#475569` (Slate-600) | `#94a3b8` (Slate-400) | 描述说明、表格辅助信息 |
| **Text Dim** (微弱文字) | `#94a3b8` (Slate-400) | `#64748b` (Slate-500) | 时间戳、流水编号、未获得状态 |

### 2. 圆角与边框系统 (Borders & Radius)
* **边框线（Border）**：统一为 `1px solid var(--border)`，严禁使用粗边框或高反差黑边。
* **圆角阶梯**：
  * 大板块 Bento 容器：`border-radius: 12px;`
  * 按钮、卡片单元：`border-radius: 8px;`
  * 状态小标签 (Badge)：`border-radius: 4px;`
  * 强调指示胶囊：`border-radius: 9999px;`

### 3. 排版与等宽数字 (Typography)
* **等宽数字支持**：钱包余额、打卡倒计时、流水金额、排名大字必须设置 `font-variant-numeric: tabular-nums`，数字跳动时字符宽度绝对恒定，彻底避免文字颤抖。
* **大数字排版层次**：
  * 关键资产数字采用 `font-weight: 800; letter-spacing: -0.04em;`
  * 单位（“分”、“LDC”）字号缩小至数字的 35%~40%，并以次级颜色（Text Muted）置于右上角或右下角对齐。

---

## 三、 各核心页面交互与布局重构规格

### 1. 全局导航栏 (Global Sticky Header)
* **定位**：全宽顶吸，内容宽度限定为 `max-width: 1280px` 居中。
* **左侧**：
  * 品牌标识 `提肛打卡` 搭配精致呼吸小微标，右侧伴随极简 `DAILY` 状态小胶囊。
* **中间导航链**：
  * 路由项：`首页`、`提肛练习`、`商店`、`称号`、`赞助`、`管理`；
  * 当前激活态为底部 2px 品牌色微滑块或轻微高亮胶囊底色，鼠标悬停带平滑过渡。
* **右侧功能区**：
  * 主题模式切换（浅色 ☀️ / 深色 🌙 / 跟随系统 💻，单触无感切换）；
  * 偏好设置齿轮 ⚙️（滑出抽屉或呼出半透明轻量弹窗）；
  * 用户登录状态 Pill：已登录展示 `@username` 与头像小标，未登录展示醒目的快捷授权登录按键。

---

### 2. 商店与积分中心 (Shop Page) —— 重点重构

#### A. 顶部吸顶资产状态条 (Sticky Asset Bar)
* 页面向下滚动时，次级状态条平滑吸顶在导航栏下方：
  * **左侧可用积分**：`50,000 积分`
  * **特权折扣徽章**：`👑 UR 特权：全店 95 折已激活（今日还可省 500 积分）`
  * **全站 LDC 每日额度指示**：微缩扁平进度条显示 `剩余 800.00 / 800.00 LDC`

#### B. 主体采用 40% : 60% 的现代 Bento 左右双栏结构
```
+-----------------------------------------------------------------------------------------+
|                                  [Global Sticky Header]                                 |
+-----------------------------------------------------------------------------------------+
|                               [Page Hero & 资产概览大看板]                                |
+----------------------------------------------------+------------------------------------+
|  左栏 (40% 宽度): 资产与记录仪表盘                      |  右栏 (60% 宽度): 现代化商品陈列展柜   |
|                                                    |                                    |
|  [ 个人钱包明细面板 ]                                 |  [ 分类筛选器: 全部 | 抽卡券 | 额度 ]  |
|  - 50,000 可用积分 (大字体等宽数字)                     +------------------------------------+
|  - 快捷打卡赚积分 / 前往称号抽卡 按钮                 |  [ 商品陈列网格 Bento Grid (2列) ]   |
|                                                    |  +----------------+ +----------------+ |
|  [ 记录选项卡 (切换零抖动) ]                          |  | 单抽券 (1 抽)   | | 十连券 (10 抽) | |
|  - Tab 1: 📦 兑换发货记录 (自动转账流水)              |  | 50 积分 (折47) | | 475 积分      | |
|  - Tab 2: 🧾 积分变动明细 (打卡/退款/消费)            |  | [立即兑换]      | | [立即兑换]     | |
|  - 纯平极简表格，支持横向自适应与状态微标签            |  +----------------+ +----------------+ |
+----------------------------------------------------+------------------------------------+
```

#### C. 商品卡片现代设计细节 (Product Card Spec)
* **外框**：`1px solid var(--border)`，无笨重阴影，悬停时产生轻微上浮（-2px）与细微主色边框发光；
* **头部**：左侧轻量徽章（`🎟️ 抽卡券` 或 `🪙 LDC 自动发货`），右侧高亮显示权益（`+100 抽` 或 `+50 LDC`）；
* **标题与简介**：两行高度锁定，超长省略，保持所有卡片在任何屏幕下高度绝对一致；
* **限购提示**：以低饱和微字呈现，避免色彩干扰；
* **底部价格区**：原价划线置灰，折后价以大号字鲜亮展示；
* **固定尺寸兑换按钮**：固定宽度，点击后出现内嵌 Spinner，绝不撑大卡片尺寸。

---

### 3. 首页打卡与今日领奖台 (Home Page)

#### A. 核心操作舞台（固定高度，彻底消除上下抖动）
* 设定舞台容器 `min-height: 480px`，居中对齐；
* **未打卡 / 打卡中**：
  * 精致圆环呼吸动效（SVG 进度条配合渐变光晕），中心显示“第 X / 3 次”或“倒计时秒数”；
  * 文字提示“轻轻收紧，缓慢放松”，点击任意区域产生轻快物理微触感；
* **打卡成功 / 已打卡**：
  * 呼吸环淡出，原位平滑淡入**「今日打卡战报」**；
  * 突出显示：`今日第 1 位完成打卡`，奖励 `+1000 站内积分`；
  * UR 特权加成高亮显示，一键直达积分商城。

#### B. 底部双栏信息区
* **左：今日打卡排行榜**：
  * 冠军、亚军、季军冠以专属金属微光勋章，下方展示打卡时间与获得积分；
* **右：打卡规则与奖金池说明**：
  * 阶梯奖励（前10名 1000分、前20名 500分…）、每日开放时段说明。

---

### 4. 称号与抽卡中心 (Titles Page)

* **顶部控制台**：
  * 拥有券数量卡片（单抽、十连、百连）横向排开；
  * 当前佩戴称号徽章与全站加成特权（如 UR 95折特权生效中）。
* **抽卡互动舞台**：
  * 质感操作键：单抽、十连、百连按钮；
  * 抽卡动画：3D 卡牌翻牌阵列，金色/紫色/红色稀有度流光，点击“再来一次”不引起页面晃动。
* **图鉴展览室 (Bento Gallery)**：
  * 分类 Filter（全部 / UR / SSR / SR / R / N，已拥有 / 未解锁）；
  * 每张卡牌展示定制精美图标、稀有度标识、获取时间与佩戴按钮。

---

## 四、 直接提供给 GPT / Midjourney 的出图提示词 (AI Prompt)

你可以将以下提示词直接复制并发送给 **GPT-4o** 或 **Midjourney** 进行出图：

### Prompt 1：商店与积分中心 (Desktop 1440px 主视图)
```text
Please create a high-resolution, ultra-detailed desktop web UI design mockup (1440x900 resolution) for the "Shop & Points Center" of a modern daily health and gamification web application.

Design Style:
- Inspired by modern high-end SaaS products like Linear.app, Vercel, Raycast, and Apple Developer.
- Layout: Modern Bento Grid architecture with clean 1px semi-transparent borders. NO chunky rounded bubbles, NO heavy blurry drop-shadows. Micro-radius (10px to 12px) throughout.
- Color Scheme: Modern Dark Mode (Deep Charcoal #090d16 background, #111827 surface layer, bright teal #14b8a6 primary accent, luxury amber gold #f59e0b for VIP/UR privilege badges).

Header Component:
- A sleek, sticky, frosted-glass header with Logo "KegeCheckin", clean text links (Home, Practice, Shop [active], Titles, Donate, Admin), theme toggle icon, and a user profile pill ("@yintian • 50,000 pts").

Page Layout (Two-Column Bento Grid):
1. Sticky Asset Bar:
   - Floating just below header: compact stats displaying "Wallet: 50,000 Points", "👑 UR Privilege: 5% OFF Activated (Saved 120/500 today)", and "Daily LDC Pool Remaining: 800.00 / 800.00".
2. Left Column (40% width):
   - Personal Wallet Card with large, elegant tabular typography ("50,000 PTS"), quick CTA buttons ("Earn via Check-in", "Gacha Badges").
   - Sleek Tabbed List: Tabs for "📦 Order Delivery History" vs "🧾 Points Ledger" with minimalist tabular data rows, green status pills ("Automated Delivery Success"), and micro timestamps.
3. Right Column (60% width):
   - Product Showcase Grid (2 columns of clean product cards):
     * Ticket items: "Single Draw Ticket", "10-Draw Ticket (+10 Draws)", "100-Draw Ticket (+100 Draws)".
     * Currency items: "10 LDC Transfer", "50 LDC Transfer".
     * Each card has: category tag at top-left, big bold reward (+100 Draws), strikethrough original price (4500) vs glowing teal discounted price (4275 pts), and a sleek fixed-width "Redeem" button.

Overall Vibe:
- Professional, visually balanced, pixel-perfect alignment, zero visual clutter, tech-forward, and premium.
```

---

### Prompt 2：首页打卡与灵动呼吸环 (Interactive Stage)
```text
Please design a modern, minimalist desktop web application UI (1440x900) for "Daily Check-in & Breathing Exercise".

Design Aesthetic:
- Ultra-clean light/dark theme fusion inspired by Apple Fitness and Linear.
- Center Hero Stage:
  * A luminous, glowing circular breathing ring with a smooth SVG progress arc (Teal #0d9488 with soft ambient halo).
  * Center of ring shows: "Step 1 of 3", countdown timer "00:08", and gentle instructional text "Inhale & Tighten gently...".
  * Sub-text below: "Click anywhere or press Spacebar to begin".
- Bottom Bento Row:
  * Left Card: "Today's Leaderboard" displaying top rankers with metallic gold/silver/bronze badge avatars and completion timestamps.
  * Right Card: "Check-in Rewards" showing tiered point rules (1st-10th: 1000 pts, 11th-20th: 500 pts) and daily deadline info.
- Zero clutter, fixed container heights to prevent layout jitter, soothing and elegant healthcare aesthetic.
```

---

### Prompt 3：称号抽取与 3D 翻牌展览室 (Gacha & Badges)
```text
Please design a premium, gamified web dashboard page for "Title Badges & Gacha Room".

Design Aesthetic:
- Dark luxury cyberpunk / Raycast aesthetic (#090d16 canvas).
- Top Console: Sleek inventory counters for "Single Ticket: 10", "10-Draw Ticket: 5", "100-Draw Ticket: 2", and "Equipped: [Grand Master of Kegel - UR]".
- Center Draw Arena:
  * Three sleek metallic action buttons: [Draw x1], [Draw x10 - Guaranteed SR], [Draw x100 - Guaranteed SSR].
  * Visual showcase of cards flipping in 3D perspective with holographic gold, purple, and rainbow light streaks.
- Bottom Showcase:
  * Filterable Badge Gallery with rarity filters (All, UR, SSR, SR, R, N).
  * Grid of badges displayed like modern trophy medals with locked/unlocked glowing state.
```

---

## 五、 技术实现要求与验收标准 (Checklist)

| 检查项 | 技术验收准则 | 状态 |
| :--- | :--- | :---: |
| **1. 滚动条跳动消除** | 全局启用 `html { scrollbar-gutter: stable; }`，切换 Tab 或数据加载绝无横向 1px 抖动 | 待实施 |
| **2. 全局 Header 吸顶** | 页面向下滚动任意深度，全局导航稳稳常驻顶部，背景带 20px 磨砂毛玻璃透光 | 待实施 |
| **3. 次级资产条吸顶** | 商店与称号页长列表滚动时，核心资产信息（积分/券）无缝微缩吸顶 | 待实施 |
| **4. 去除臃肿圆角** | 全面替换粗大圆角为 `10px ~ 12px` 微圆角，移除厚重脏阴影，改为 1px 细微半透明边框 | 待实施 |
| **5. 等宽数字对齐** | 钱包、流水、倒计时启用 `tabular-nums`，数值变化时字符不左右晃动 | 待实施 |
| **6. 按钮尺寸防溢出** | 异步操作按钮设置显式 `min-width`，状态切换（“兑换中…”）不撑大外层网格 | 待实施 |
| **7. 首页舞台恒高** | 首页打卡区设置固定最小高度与淡入淡出，打卡完成与领奖台切换无垂直跳跃 | 待实施 |

---

*文档已写入完毕，可直接复制 Prompt 进行 AI 出图，待设计图生成后即可开始按图逐项实施。*

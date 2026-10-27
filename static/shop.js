"use strict";

const $ = (selector) => document.querySelector(selector);
const state = { data: null, loading: false, selectedProduct: null, purchasing: false };

function notify(message) {
  const notice = $("#notice");
  notice.textContent = message;
  notice.hidden = false;
  clearTimeout(notify.timer);
  notify.timer = setTimeout(() => { notice.hidden = true; }, 4000);
}

function displayTime(value) {
  if (!value) return "—";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? String(value) : date.toLocaleString("zh-CN", { hour12: false });
}

function renderProducts(products = []) {
  const grid = $("#productsGrid");
  if (!grid) return;
  grid.replaceChildren();

  if (!products.length) {
    const empty = document.createElement("div");
    empty.style.gridColumn = "1 / -1";
    empty.style.textAlign = "center";
    empty.style.padding = "48px 24px";
    empty.style.color = "var(--text-dim)";
    empty.innerHTML = `
      <div style="font-size: 32px; margin-bottom: 12px;">🪙</div>
      <div style="font-size: 15px; font-weight: 600; color: var(--text-main); margin-bottom: 4px;">暂无上架商品</div>
      <div style="font-size: 13px;">管理员可在后台添加 LDC 自动发货商品。</div>
    `;
    grid.append(empty);
    return;
  }

  const user = state.data?.user;
  const balance = user && state.data?.wallet ? Number(state.data.wallet.balance) : 0;
  const quotaRemaining = Number(state.data?.quota?.remaining ?? 0);

  for (const item of products) {
    const card = document.createElement("article");
    card.className = "product-card";

    // Top badge
    const badgeRow = document.createElement("div");
    badgeRow.style.display = "flex";
    badgeRow.style.justifyContent = "space-between";
    badgeRow.style.alignItems = "center";
    badgeRow.style.marginBottom = "12px";

    const badge = document.createElement("span");
    badge.className = "product-badge";
    badge.textContent = `${item.category || "LDC"} 自动发货`;
    badgeRow.append(badge);

    const ldcAmountBadge = document.createElement("span");
    ldcAmountBadge.style.fontSize = "13px";
    ldcAmountBadge.style.fontWeight = "700";
    ldcAmountBadge.style.color = "var(--emerald)";
    ldcAmountBadge.textContent = `+${item.ldc_amount} LDC`;
    badgeRow.append(ldcAmountBadge);

    const name = document.createElement("h3");
    name.className = "product-name";
    name.textContent = item.name;

    const desc = document.createElement("p");
    desc.className = "product-desc";
    desc.textContent = item.description || "购买后系统将自动转账发货至你的 Linux DO 账户。";

    // Quota limits row
    const limitsWrap = document.createElement("div");
    limitsWrap.style.fontSize = "12px";
    limitsWrap.style.color = "var(--text-dim)";
    limitsWrap.style.marginBottom = "14px";
    limitsWrap.style.display = "flex";
    limitsWrap.style.flexDirection = "column";
    limitsWrap.style.gap = "4px";

    if (item.user_daily_limit > 0) {
      const rem = item.user_remaining !== null ? item.user_remaining : item.user_daily_limit;
      const userLimText = document.createElement("span");
      userLimText.textContent = `个人今日剩余：${rem} / ${item.user_daily_limit} 份`;
      if (rem <= 0) userLimText.style.color = "#dc2626";
      limitsWrap.append(userLimText);
    }

    if (item.total_daily_limit > 0) {
      const totRem = item.total_remaining !== null ? item.total_remaining : item.total_daily_limit;
      const totLimText = document.createElement("span");
      totLimText.textContent = `全站今日剩余：${totRem} / ${item.total_daily_limit} 份`;
      if (totRem <= 0) totLimText.style.color = "#dc2626";
      limitsWrap.append(totLimText);
    }

    // Price & Exchange Action Button
    const footer = document.createElement("div");
    footer.style.display = "flex";
    footer.style.justifyContent = "space-between";
    footer.style.alignItems = "center";
    footer.style.marginTop = "auto";
    footer.style.paddingTop = "12px";
    footer.style.borderTop = "1px solid var(--border-light)";

    const price = document.createElement("span");
    price.className = "product-price";
    price.textContent = `${item.points_price} 积分`;

    const buyBtn = document.createElement("button");
    buyBtn.type = "button";
    buyBtn.className = "btn-primary";
    buyBtn.style.padding = "6px 14px";
    buyBtn.style.fontSize = "13px";

    if (!user) {
      buyBtn.textContent = "登录后兑换";
      buyBtn.onclick = () => window.location.assign("/auth/linuxdo/start?next=/shop");
    } else if (Number(item.ldc_amount) > quotaRemaining) {
      buyBtn.textContent = quotaRemaining <= 0 ? "今日兑换已停止" : "LDC 额度不足";
      buyBtn.disabled = true;
    } else if (item.user_daily_limit > 0 && item.user_remaining <= 0) {
      buyBtn.textContent = "今日已达限购";
      buyBtn.disabled = true;
    } else if (item.total_daily_limit > 0 && item.total_remaining <= 0) {
      buyBtn.textContent = "今日已抢光";
      buyBtn.disabled = true;
    } else if (balance < item.points_price) {
      buyBtn.textContent = "积分不足";
      buyBtn.disabled = true;
    } else {
      buyBtn.textContent = "立即兑换";
      buyBtn.onclick = () => openPurchaseModal(item);
    }

    footer.append(price, buyBtn);
    card.append(badgeRow, name, desc, limitsWrap, footer);
    grid.append(card);
  }
}

function renderPurchases(purchases = []) {
  const body = $("#purchasesRows");
  if (!body) return;
  body.replaceChildren();

  if (!state.data?.user) {
    const row = document.createElement("tr");
    const cell = document.createElement("td");
    cell.colSpan = 4;
    cell.style.textAlign = "center";
    cell.style.color = "var(--text-dim)";
    cell.style.padding = "24px 16px";
    cell.textContent = "登录 LINUX DO 后可查看个人商品兑换记录。";
    row.append(cell);
    body.append(row);
    return;
  }

  if (!purchases.length) {
    const row = document.createElement("tr");
    const cell = document.createElement("td");
    cell.colSpan = 4;
    cell.style.textAlign = "center";
    cell.style.color = "var(--text-dim)";
    cell.style.padding = "24px 16px";
    cell.textContent = "暂无兑换记录，使用积分可兑换上方 LDC。";
    row.append(cell);
    body.append(row);
    return;
  }

  const statusMap = {
    success: { text: "自动发货成功", color: "var(--emerald)" },
    simulated: { text: "模拟发货成功", color: "var(--emerald)" },
    pending: { text: "转账处理中", color: "#d97706" },
    failed: { text: "失败(已退还积分)", color: "#dc2626" },
    uncertain: { text: "待核对流水", color: "#d97706" }
  };

  for (const item of purchases) {
    const row = document.createElement("tr");

    const timeCell = document.createElement("td");
    timeCell.textContent = displayTime(item.created_at);

    const nameCell = document.createElement("td");
    nameCell.textContent = `${item.product_name} (+${item.ldc_amount} LDC)`;

    const costCell = document.createElement("td");
    costCell.style.color = "var(--text-muted)";
    costCell.style.fontWeight = "600";
    costCell.textContent = `-${item.points_cost} 分`;

    const stCell = document.createElement("td");
    const conf = statusMap[item.status] || { text: item.status, color: "var(--text-dim)" };
    const pill = document.createElement("span");
    pill.className = `status-pill ${item.status === "success" || item.status === "simulated" ? "credited" : ""}`;
    pill.style.color = conf.color;
    pill.textContent = conf.text;
    stCell.append(pill);

    row.append(timeCell, nameCell, costCell, stCell);
    body.append(row);
  }
}

function renderLedger(ledger = []) {
  const body = $("#ledgerRows");
  if (!body) return;
  body.replaceChildren();

  if (!state.data?.user) {
    const row = document.createElement("tr");
    const cell = document.createElement("td");
    cell.colSpan = 4;
    cell.style.textAlign = "center";
    cell.style.color = "var(--text-dim)";
    cell.style.padding = "24px 16px";
    cell.textContent = "登录 LINUX DO 后可查看自己的站内积分流水。";
    row.append(cell);
    body.append(row);
    return;
  }

  if (!ledger.length) {
    const row = document.createElement("tr");
    const cell = document.createElement("td");
    cell.colSpan = 4;
    cell.style.textAlign = "center";
    cell.style.color = "var(--text-dim)";
    cell.style.padding = "24px 16px";
    cell.textContent = "还没有积分记录，先去完成今日打卡赚积分吧。";
    row.append(cell);
    body.append(row);
    return;
  }

  const kindMap = {
    checkin: "每日打卡奖励",
    shop_purchase: "商品兑换扣除",
    shop_refund: "发货失败退款"
  };

  for (const entry of ledger) {
    const row = document.createElement("tr");

    const timeCell = document.createElement("td");
    timeCell.textContent = displayTime(entry.created_at);

    const kindCell = document.createElement("td");
    kindCell.textContent = kindMap[entry.kind] || entry.kind;

    const deltaCell = document.createElement("td");
    deltaCell.style.fontWeight = "600";
    if (entry.delta > 0) {
      deltaCell.style.color = "var(--primary)";
      deltaCell.textContent = `+${entry.delta}`;
    } else {
      deltaCell.style.color = "#dc2626";
      deltaCell.textContent = `${entry.delta}`;
    }

    const balanceCell = document.createElement("td");
    balanceCell.textContent = `${entry.balance_after} 积分`;

    row.append(timeCell, kindCell, deltaCell, balanceCell);
    body.append(row);
  }
}

function render() {
  const { user, oauth_ready, wallet, quota, products = [], purchases = [], ledger = [] } = state.data;

  const btn = $("#accountButton");
  btn.textContent = user ? `@${user.username} · 退出` : oauth_ready ? "LINUX DO 登录" : "登录暂未配置";
  btn.disabled = !user && !oauth_ready;

  $("#walletBalance").textContent = user && wallet ? Number(wallet.balance).toLocaleString() : "—";
  $("#walletNote").textContent = user
    ? `当前登录账号：@${user.username}`
    : "登录后即可使用站内积分兑换 LDC 并自动发货。";

  if (quota) {
    $("#quotaSummary").textContent = `今日全站 LDC 兑换额度：已用 ${quota.used} / ${quota.limit} LDC（剩余 ${quota.remaining} LDC）`;
  }

  renderProducts(products);
  renderPurchases(purchases);
  renderLedger(ledger);
}

function openPurchaseModal(product) {
  state.selectedProduct = product;
  const user = state.data?.user;
  $("#purchaseDialogTitle").textContent = `确认兑换：${product.name}`;
  $("#purchaseDialogDesc").innerHTML = `
    即将消耗 <strong>${product.points_price} 积分</strong> 兑换 <strong>${product.ldc_amount} LDC</strong>。<br />
    发货方式：系统自动转账至当前登录用户 <strong>@${user?.username || ""}</strong> 的 Linux DO 账户。
  `;
  $("#purchaseDialog").showModal();
}

$("#purchaseCancel").addEventListener("click", () => {
  $("#purchaseDialog").close();
});

$("#purchaseForm").addEventListener("submit", async (event) => {
  event.preventDefault();
  if (state.purchasing || !state.selectedProduct) return;
  state.purchasing = true;
  const submitBtn = $("#purchaseSubmit");
  submitBtn.disabled = true;
  submitBtn.textContent = "正在扣减积分并自动发货…";

  try {
    const requestKey = `ldc-purchase:${state.data.user.id}:${state.selectedProduct.id}`;
    let requestId = sessionStorage.getItem(requestKey);
    if (!requestId) {
      requestId = crypto.randomUUID();
      sessionStorage.setItem(requestKey, requestId);
    }
    const response = await fetch("/api/shop/purchase", {
      method: "POST",
      credentials: "same-origin",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ product_id: state.selectedProduct.id, request_id: requestId })
    });
    const data = await response.json().catch(() => { throw new Error("服务器响应无法解析"); });
    if (!response.ok || data.ok === false) throw new Error(data.error || `兑换失败 (${response.status})`);
    if (data.status !== "pending" && data.status !== "uncertain") {
      sessionStorage.removeItem(requestKey);
    }

    $("#purchaseDialog").close();
    if (data.status === "success" || data.status === "simulated") {
      notify(`🎉 兑换成功！${state.selectedProduct.ldc_amount} LDC 已自动发货${data.trade_no ? `（流水号: ${data.trade_no}）` : ""}`);
    } else if (data.status === "failed") {
      notify(`自动发货失败：${data.error || "未知原因"}，消耗积分已全额自动退还。`);
    } else {
      notify(`转账请求已提交，结果待核对：${data.error || "请稍后查看状态"}`);
    }
    await refresh();
  } catch (error) {
    notify(`兑换失败：${error.message}`);
  } finally {
    state.purchasing = false;
    submitBtn.disabled = false;
    submitBtn.textContent = "确认兑换并自动发货";
  }
});

async function refresh() {
  if (state.loading) return;
  state.loading = true;
  const btn = $("#refreshButton");
  if (btn) {
    btn.disabled = true;
    btn.textContent = "正在刷新…";
  }

  try {
    const response = await fetch("/api/shop", { credentials: "same-origin", cache: "no-store" });
    const data = await response.json().catch(() => { throw new Error("响应数据无法解析"); });
    if (!response.ok || data.ok === false) throw new Error(data.error || `请求失败 (${response.status})`);
    state.data = data;
    render();
  } catch (error) {
    notify(`无法读取数据：${error.message}`);
  } finally {
    state.loading = false;
    if (btn) {
      btn.disabled = false;
      btn.textContent = "刷新状态";
    }
  }
}

$("#accountButton").addEventListener("click", () => {
  if (state.data?.user) window.location.assign("/auth/logout");
  else if (state.data && !state.data.oauth_ready) notify("LINUX DO 登录暂未配置。");
  else window.location.assign("/auth/linuxdo/start?next=/shop");
});

$("#refreshButton").addEventListener("click", () => { void refresh(); });
document.addEventListener("visibilitychange", () => { if (!document.hidden) void refresh(); });
void refresh();

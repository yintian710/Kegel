"use strict";

const $ = (selector) => document.querySelector(selector);
const state = { data: null, loading: false, creating: false, pendingTimer: null };

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

function renderBoard(leaderboard = []) {
  const body = $("#donationBoardRows");
  if (!body) return;
  body.replaceChildren();

  if (!leaderboard.length) {
    const row = document.createElement("tr");
    const cell = document.createElement("td");
    cell.colSpan = 4;
    cell.style.textAlign = "center";
    cell.style.color = "var(--text-dim)";
    cell.style.padding = "32px 16px";
    cell.textContent = "还没有已确认到账的 LDC 赞助。赞助经核验到账后会显示在这里。";
    row.append(cell);
    body.append(row);
    return;
  }

  for (const entry of leaderboard) {
    const row = document.createElement("tr");

    const rankCell = document.createElement("td");
    if (entry.rank <= 3) {
      const badge = document.createElement("span");
      badge.className = `rank-badge rank-${entry.rank}`;
      badge.textContent = entry.rank;
      rankCell.append(badge);
    } else {
      rankCell.textContent = entry.rank;
    }

    const userCell = document.createElement("td");
    userCell.textContent = `@${entry.username}`;

    const amountCell = document.createElement("td");
    amountCell.style.color = "var(--primary)";
    amountCell.style.fontWeight = "700";
    amountCell.textContent = `${entry.amount} LDC`;

    const countCell = document.createElement("td");
    countCell.style.textAlign = "right";
    countCell.textContent = `${entry.count} 次`;

    row.append(rankCell, userCell, amountCell, countCell);
    body.append(row);
  }
}

function renderMyOrders(orders = []) {
  const body = $("#myDonationsRows");
  if (!body) return;
  body.replaceChildren();

  if (!state.data?.user) {
    const row = document.createElement("tr");
    const cell = document.createElement("td");
    cell.colSpan = 4;
    cell.style.textAlign = "center";
    cell.style.color = "var(--text-dim)";
    cell.style.padding = "24px";
    cell.textContent = "登录 LINUX DO 后可查看自己的赞助订单。";
    row.append(cell);
    body.append(row);
    return;
  }

  if (!orders.length) {
    const row = document.createElement("tr");
    const cell = document.createElement("td");
    cell.colSpan = 4;
    cell.style.textAlign = "center";
    cell.style.color = "var(--text-dim)";
    cell.style.padding = "24px";
    cell.textContent = "你还没有赞助订单。赞助不会增加站内积分。";
    row.append(cell);
    body.append(row);
    return;
  }

  for (const order of orders) {
    const row = document.createElement("tr");

    const timeCell = document.createElement("td");
    timeCell.textContent = displayTime(order.created_at);

    const amountCell = document.createElement("td");
    amountCell.style.fontWeight = "600";
    amountCell.textContent = `${order.amount} LDC`;

    const statusCell = document.createElement("td");
    const statusPill = document.createElement("span");
    statusPill.className = `status-pill ${order.status === "paid" ? "credited" : ""}`;
    statusPill.textContent = order.status === "paid" ? "已确认到账" : "待确认到账";
    statusCell.append(statusPill);

    const orderCell = document.createElement("td");
    orderCell.style.fontFamily = "monospace";
    orderCell.style.fontSize = "12px";
    orderCell.textContent = order.order_no.slice(0, 14) + "…";

    row.append(timeCell, amountCell, statusCell, orderCell);
    body.append(row);
  }
}

function render() {
  const { donation_ready, donation_leaderboard = [], donation_orders = [] } = state.data;

  window.SiteNavigation.update(state.data);

  const badge = $("#donateStatusBadge");
  if (!donation_ready) {
    badge.textContent = "LDC 赞助接口暂未配置";
    badge.style.color = "var(--text-dim)";
    $("#sponsorSubmitBtn").disabled = true;
  } else {
    badge.textContent = "安全支付 · 实时到账";
    badge.style.color = "var(--emerald)";
    $("#sponsorSubmitBtn").disabled = state.creating;
  }

  renderBoard(donation_leaderboard);
  renderMyOrders(donation_orders);
}

function submitPayment(payment) {
  const action = new URL(payment.action);
  const localHttp = action.protocol === "http:" && ["localhost", "127.0.0.1"].includes(action.hostname);
  if ((action.protocol !== "https:" && !localHttp) || action.username || action.password) {
    throw new Error("支付入口无效，请稍后重试。");
  }
  const fields = Object.entries(payment.fields);
  if (!fields.length || fields.some(([, value]) => typeof value !== "string")) {
    throw new Error("支付信息无法读取，请刷新订单状态后重试。");
  }
  const form = document.createElement("form");
  form.method = "post";
  form.action = action.href;
  form.hidden = true;
  for (const [name, value] of fields) {
    const input = document.createElement("input");
    input.type = "hidden";
    input.name = name;
    input.value = value;
    form.append(input);
  }
  document.body.append(form);
  try {
    HTMLFormElement.prototype.submit.call(form);
  } finally {
    form.remove();
  }
}


async function refresh() {
  if (state.loading) return;
  state.loading = true;
  clearTimeout(state.pendingTimer);

  const btn = $("#refreshBoardBtn");
  if (btn) btn.disabled = true;

  try {
    const response = await fetch("/api/donations", { credentials: "same-origin", cache: "no-store" });
    const data = await response.json().catch(() => { throw new Error("响应数据无法解析"); });
    if (!response.ok || data.ok === false) throw new Error(data.error || `请求失败 (${response.status})`);
    state.data = data;
    render();

    // Schedule pending refresh if there are created orders
    if (!document.hidden && data.user && data.donation_orders?.some((o) => o.status === "created")) {
      state.pendingTimer = setTimeout(() => { void refresh(); }, 15000);
    }
  } catch (error) {
    notify(`数据更新失败：${error.message}`);
  } finally {
    state.loading = false;
    if (btn) btn.disabled = false;
  }
}

// Amount chips click
document.querySelectorAll(".amount-chip").forEach((chip) => {
  chip.addEventListener("click", () => {
    document.querySelectorAll(".amount-chip").forEach((c) => c.classList.remove("selected"));
    chip.classList.add("selected");
    $("#donationAmount").value = chip.dataset.amount;
  });
});

$("#donationAmount").addEventListener("input", () => {
  const val = Number($("#donationAmount").value).toFixed(2);
  document.querySelectorAll(".amount-chip").forEach((chip) => {
    chip.classList.toggle("selected", chip.dataset.amount === val);
  });
});

$("#donationForm").addEventListener("submit", async (event) => {
  event.preventDefault();
  if (state.creating || !$("#donationForm").reportValidity()) return;
  if (!state.data?.user) {
    window.SiteNavigation.login();
    return;
  }

  const amount = Number($("#donationAmount").value).toFixed(2);
  state.creating = true;
  const submitBtn = $("#sponsorSubmitBtn");
  submitBtn.disabled = true;
  submitBtn.textContent = "正在创建订单…";

  try {
    const response = await fetch("/api/donations/create", {
      method: "POST",
      credentials: "same-origin",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ amount }),
    });
    if (response.status === 401) {
      window.SiteNavigation.login();
      return;
    }
    const data = await response.json().catch(() => { throw new Error("服务器响应格式不正确"); });
    if (!response.ok || data.ok === false) throw new Error(data.error || `创建失败 (${response.status})`);

    submitBtn.textContent = "正在前往支付平台…";
    submitPayment(data.payment);
  } catch (error) {
    notify(`发起赞助失败：${error.message}`);
    submitBtn.disabled = false;
    submitBtn.textContent = "赞助 LDC →";
  } finally {
    state.creating = false;
  }
});


$("#refreshBoardBtn").addEventListener("click", () => { void refresh(); });
document.addEventListener("visibilitychange", () => {
  if (document.hidden) clearTimeout(state.pendingTimer);
  else void refresh();
});

void refresh();

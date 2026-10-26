"use strict";

const $ = (selector) => document.querySelector(selector);
const tokenKey = "checkin_admin_token";
const state = { token: "", data: null, busy: false, action: null };
const rewardLabels = { unclaimed: "未领取", credited: "已记入钱包", none: "无奖励" };

function notify(message) {
  const notice = $("#notice");
  notice.textContent = message;
  notice.hidden = false;
  clearTimeout(notify.timer);
  notify.timer = setTimeout(() => { notice.hidden = true; }, 4000);
}

async function api(path = "/api/admin", body) {
  const response = await fetch(path, {
    method: body === undefined ? "GET" : "POST",
    credentials: "same-origin",
    headers: { "Content-Type": "application/json", "X-Admin-Token": state.token },
    ...(body === undefined ? {} : { body: JSON.stringify(body) }),
  });
  const data = await response.json().catch(() => { throw new Error("无法读取服务器响应。"); });
  if (!response.ok || data.ok === false) {
    if (response.status === 401 || response.status === 403) {
      state.token = "";
      try { sessionStorage.removeItem(tokenKey); } catch {}
      showLogin();
    }
    throw new Error(data.error || `请求失败（${response.status}）`);
  }
  return data;
}

function showLogin() {
  $("#confirmationDialog").close();
  $("#dashboard").hidden = true;
  $("#loginPanel").hidden = false;
}

function setBusy(value) {
  state.busy = value;
  document.querySelectorAll("button").forEach((btn) => { btn.disabled = value; });
  if (!value && state.data) {
    $("#openButton").disabled = state.data.status.is_open;
  }
}

function cell(row, text, className) {
  const el = document.createElement("td");
  el.textContent = text == null || text === "" ? "—" : String(text);
  if (className) el.className = className;
  row.append(el);
  return el;
}

function emptyTable(body, cols, msg) {
  const row = document.createElement("tr");
  const el = cell(row, msg);
  el.colSpan = cols;
  el.style.textAlign = "center";
  el.style.color = "var(--text-dim)";
  el.style.padding = "24px 16px";
  body.append(row);
}

function actionButton(text, handler, isDanger = false) {
  const btn = document.createElement("button");
  btn.type = "button";
  btn.className = "btn-secondary";
  btn.style.padding = "4px 10px";
  btn.style.fontSize = "12px";
  if (isDanger) {
    btn.style.color = "#dc2626";
    btn.style.borderColor = "#fecaca";
  }
  btn.textContent = text;
  btn.addEventListener("click", handler);
  return btn;
}

function addRewardRow(tier = { through: "", amount: 0 }) {
  const row = document.createElement("tr");
  const rank = document.createElement("input");
  rank.type = "number";
  rank.min = "1";
  rank.step = "1";
  rank.required = true;
  rank.value = tier.through;
  rank.className = "input-text";
  rank.style.padding = "6px 8px";
  rank.dataset.field = "through";

  const amount = document.createElement("input");
  amount.type = "number";
  amount.min = "0";
  amount.max = "100000000";
  amount.step = "1";
  amount.required = true;
  amount.value = tier.amount;
  amount.className = "input-text";
  amount.style.padding = "6px 8px";
  amount.dataset.field = "amount";

  cell(row, "").replaceChildren(rank);
  cell(row, "").replaceChildren(amount);
  cell(row, "").replaceChildren(actionButton("移除", () => { row.remove(); }, true));
  $("#rewardRows").append(row);
}

function renderProducts(products = []) {
  const body = $("#productRows");
  body.replaceChildren();
  if (!products.length) {
    emptyTable(body, 8, "暂无商品记录，在左侧表单中添加商品。");
    return;
  }

  for (const item of products) {
    const row = document.createElement("tr");
    cell(row, `#${item.id}`);
    const catCell = cell(row, item.category || "LDC");
    catCell.style.fontWeight = "600";
    catCell.style.color = "var(--primary)";

    cell(row, item.name);

    const priceCell = cell(row, `${item.points_price} 分`);
    priceCell.style.fontWeight = "600";

    const ldcCell = cell(row, `${item.ldc_amount} LDC`);
    ldcCell.style.fontWeight = "700";
    ldcCell.style.color = "var(--emerald)";

    const userLim = item.user_daily_limit > 0 ? `${item.user_daily_limit} 份/人` : "不限";
    const totLim = item.total_daily_limit > 0 ? `${item.total_daily_limit} 份/天` : "不限";
    cell(row, `${userLim} / ${totLim}`);

    const statusCell = cell(row, item.is_active ? "在售中" : "已下架");
    statusCell.style.color = item.is_active ? "var(--emerald)" : "var(--text-dim)";

    const act = cell(row, "");
    act.style.display = "flex";
    act.style.gap = "6px";

    const editBtn = actionButton("编辑", () => {
      $("#productId").value = item.id;
      $("#productCategory").value = item.category || "LDC";
      $("#productName").value = item.name;
      $("#productDescription").value = item.description || "";
      $("#productPrice").value = item.points_price;
      $("#productLdcAmount").value = item.ldc_amount || "1.00";
      $("#productUserLimit").value = item.user_daily_limit || 0;
      $("#productTotalLimit").value = item.total_daily_limit || 0;
      $("#productActive").checked = item.is_active;
      $("#productFormTitle").textContent = `编辑商品 #${item.id}`;
      $("#productName").focus();
    });
    act.append(editBtn);

    if (item.is_active) {
      const archBtn = actionButton("下架", async () => {
        if (!confirm(`确定下架商品 “${item.name}” 吗？`)) return;
        setBusy(true);
        try {
          await api(`/api/admin/products/${item.id}/archive`, {});
          notify("商品已下架");
          await refresh();
        } catch (err) {
          notify(`操作失败：${err.message}`);
        } finally {
          setBusy(false);
        }
      }, true);
      act.append(archBtn);
    }

    body.append(row);
  }
}

function renderPurchases(purchases = []) {
  const body = $("#purchaseRows");
  if (!body) return;
  body.replaceChildren();
  if (!purchases.length) {
    emptyTable(body, 7, "暂无用户兑换与发货记录。");
    return;
  }

  const statusNames = {
    success: "自动发货成功",
    simulated: "模拟发货成功",
    pending: "处理中",
    failed: "失败 (已退还积分)",
    uncertain: "待人工核对"
  };

  for (const item of purchases) {
    const row = document.createElement("tr");
    const orderCell = cell(row, item.order_no);
    orderCell.style.fontFamily = "monospace";
    orderCell.style.fontSize = "12px";

    cell(row, `@${item.username} (${item.user_id})`);
    cell(row, `${item.product_name} (${item.ldc_amount} LDC)`);

    const ptsCell = cell(row, `-${item.points_cost} 分`);
    ptsCell.style.fontWeight = "600";

    const stCell = cell(row, statusNames[item.status] || item.status);
    stCell.style.fontWeight = "600";
    if (item.status === "success" || item.status === "simulated") {
      stCell.style.color = "var(--emerald)";
    } else if (item.status === "failed") {
      stCell.style.color = "#dc2626";
    } else {
      stCell.style.color = "#d97706";
    }

    cell(row, item.trade_no || item.error || "—");
    cell(row, item.created_at);

    body.append(row);
  }
}

function render() {
  const { settings, status, visits, rewards, wallets, practice_triggers = [], products = [] } = state.data;
  $("#loginPanel").hidden = true;
  $("#dashboard").hidden = false;

  // Overview metrics
  $("#adminDay").textContent = `${status.day} (北京时间) · 今日已有 ${status.total} 人完成打卡`;
  $("#openStatus").textContent = status.is_open ? "已开启" : "待开启";
  $("#openStatus").style.color = status.is_open ? "var(--emerald)" : "var(--text-dim)";
  $("#statusDetail").textContent = status.is_open ? `开放方式: ${status.open_reason || "系统"}` : "今日正常打卡尚未开放";
  $("#openButton").disabled = state.busy || status.is_open;
  $("#openButton").textContent = status.is_open ? "已开放" : "手动开启";

  $("#metricDeadline").textContent = settings.deadline;
  $("#metricStepSeconds").textContent = `${settings.min_step_seconds} 秒`;
  $("#metricQuota").textContent = `${settings.daily_points_limit} 分`;
  $("#metricQuotaSub").textContent = `已用 ${status.quota.used} 分 · 剩余 ${status.quota.remaining} 分`;

  // Settings inputs
  $("#deadline").value = settings.deadline;
  $("#minStepSeconds").value = settings.min_step_seconds;
  $("#dailyPointsLimit").value = settings.daily_points_limit;
  $("#dailyQuotaStatus").textContent = `今日已发 ${status.quota.used} / ${status.quota.limit} 分 (剩余 ${status.quota.remaining} 分)`;
  $("#conditionUrl").value = settings.condition_url || "";

  // Rewards list
  $("#rewardRows").replaceChildren();
  settings.reward_tiers.forEach(addRewardRow);

  // Products
  renderProducts(products);
  renderPurchases(state.data.purchases || []);

  // Practice triggers
  const practiceBody = $("#practiceRows");
  practiceBody.replaceChildren();
  if (!practice_triggers.length) emptyTable(practiceBody, 4, "暂无练习触发记录。");
  for (const trigger of practice_triggers) {
    const row = document.createElement("tr");
    cell(row, `@${trigger.username} · ${trigger.user_id}`);
    cell(row, `第 ${trigger.group_no} 组`);
    cell(row, trigger.created_at);
    const flowCell = cell(row, trigger.flow_id ? trigger.flow_id.slice(0, 10) + "…" : "—");
    flowCell.style.fontFamily = "monospace";
    practiceBody.append(row);
  }

  // Visits & Review
  const visitBody = $("#visitRows");
  visitBody.replaceChildren();
  if (!visits.length) emptyTable(visitBody, 4, "今日暂无访问记录。");
  for (const visit of visits) {
    const row = document.createElement("tr");
    cell(row, visit.username ? `@${visit.username}` : `访客 (${visit.user_id})`);
    cell(row, `${visit.count} 次`);
    cell(row, visit.reason || "正常访问");
    const actions = cell(row, visit.approved ? "已批准" : visit.reason ? "待确认" : "正常");
    if (visit.reason && !visit.approved) {
      actions.replaceChildren(actionButton("批准通过", () => {
        openConfirmation({
          title: "批准异常访问",
          description: `批准用户 ${visit.username || visit.user_id} 的今日打卡资格？标记原因：${visit.reason}`,
          check: "我已核实访问行为，确认解除限制。",
          path: "/api/admin/review",
          body: { user_id: visit.user_id, approved: true },
        });
      }));
    }
    visitBody.append(row);
  }

  // Rewards History
  const rewardBody = $("#rewardHistoryRows");
  rewardBody.replaceChildren();
  if (!rewards.length) emptyTable(rewardBody, 5, "暂无站内积分奖励记录。");
  for (const reward of rewards) {
    const row = document.createElement("tr");
    cell(row, `${reward.day} · #${reward.rank}`);
    cell(row, `@${reward.username}`);
    const amtCell = cell(row, `${reward.amount} 分`);
    amtCell.style.color = "var(--primary)";
    amtCell.style.fontWeight = "600";
    cell(row, rewardLabels[reward.reward_status] || reward.reward_status);
    cell(row, reward.claimed_at || "未领取");
    rewardBody.append(row);
  }

  // Wallets
  const walletBody = $("#walletRows");
  walletBody.replaceChildren();
  if (!wallets.length) emptyTable(walletBody, 2, "暂无站内积分钱包。");
  for (const wallet of wallets) {
    const row = document.createElement("tr");
    cell(row, `@${wallet.username} (${wallet.user_id})`);
    const balCell = cell(row, `${wallet.balance} 积分`);
    balCell.style.fontWeight = "700";
    balCell.style.color = "var(--primary)";
    walletBody.append(row);
  }
}

function openConfirmation(action) {
  state.action = action;
  $("#confirmationForm").reset();
  $("#confirmationTitle").textContent = action.title;
  $("#confirmationDescription").textContent = action.description;
  $("#confirmationCheckText").textContent = action.check;
  $("#confirmationDialog").showModal();
}

async function refresh() {
  state.data = await api();
  render();
}

async function saveSettings(settings, message) {
  if (state.busy) return;
  setBusy(true);
  try {
    await api("/api/admin/settings", settings);
    await refresh();
    notify(message);
  } catch (error) {
    notify(error.message);
  } finally {
    setBusy(false);
  }
}

$("#loginForm").addEventListener("submit", async (event) => {
  event.preventDefault();
  if (state.busy) return;
  state.token = $("#adminToken").value.trim();
  $("#loginError").textContent = "";
  setBusy(true);
  try {
    sessionStorage.setItem(tokenKey, state.token);
    await refresh();
    $("#adminToken").value = "";
  } catch (error) {
    try { sessionStorage.removeItem(tokenKey); } catch {}
    state.token = "";
    showLogin();
    $("#loginError").textContent = error.message;
  } finally {
    setBusy(false);
  }
});

$("#logoutButton").addEventListener("click", () => {
  try { sessionStorage.removeItem(tokenKey); } catch {}
  state.token = "";
  state.data = null;
  $("#confirmationDialog").close();
  showLogin();
  $("#adminToken").focus();
});

$("#settingsForm").addEventListener("submit", (event) => {
  event.preventDefault();
  void saveSettings({
    ...state.data.settings,
    deadline: $("#deadline").value,
    min_step_seconds: Number($("#minStepSeconds").value),
    daily_points_limit: Number($("#dailyPointsLimit").value),
    condition_url: $("#conditionUrl").value.trim(),
  }, "基础规则已更新。");
});

$("#addTierButton").addEventListener("click", () => {
  if (!state.busy) addRewardRow();
});

$("#rewardsForm").addEventListener("submit", (event) => {
  event.preventDefault();
  const tiers = [...document.querySelectorAll("#rewardRows tr")].map((row) => ({
    through: Number(row.querySelector('[data-field="through"]').value),
    amount: Number(row.querySelector('[data-field="amount"]').value),
  }));
  if (tiers.some((tier, index) => !Number.isInteger(tier.through) || tier.through <= (index ? tiers[index - 1].through : 0))) {
    notify("截止名次须为递增的正整数。");
    return;
  }
  if (tiers.some((tier) => !Number.isInteger(tier.amount) || tier.amount < 0 || tier.amount > 100000000)) {
    notify("每人站内积分须为 0 至 100000000 的整数。");
    return;
  }
  void saveSettings({ ...state.data.settings, reward_tiers: tiers }, "排名奖励设置已保存。");
});

// Product catalog form
$("#productsForm").addEventListener("submit", async (event) => {
  event.preventDefault();
  if (state.busy) return;
  const idVal = $("#productId").value;
  const body = {
    category: $("#productCategory").value || "LDC",
    name: $("#productName").value.trim(),
    description: $("#productDescription").value.trim(),
    points_price: Number($("#productPrice").value),
    ldc_amount: $("#productLdcAmount").value.trim() || "1.00",
    user_daily_limit: Number($("#productUserLimit").value) || 0,
    total_daily_limit: Number($("#productTotalLimit").value) || 0,
    is_active: $("#productActive").checked
  };
  if (idVal) body.id = Number(idVal);

  setBusy(true);
  try {
    await api("/api/admin/products", body);
    notify(idVal ? "商品已更新" : "新商品已添加并上架");
    $("#productsForm").reset();
    $("#productId").value = "";
    $("#productCategory").value = "LDC";
    $("#productLdcAmount").value = "1.00";
    $("#productUserLimit").value = "1";
    $("#productTotalLimit").value = "10";
    $("#productActive").checked = true;
    $("#productFormTitle").textContent = "添加上架商品";
    await refresh();
  } catch (err) {
    notify(`保存商品失败：${err.message}`);
  } finally {
    setBusy(false);
  }
});

$("#productReset").addEventListener("click", () => {
  $("#productsForm").reset();
  $("#productId").value = "";
  $("#productCategory").value = "LDC";
  $("#productLdcAmount").value = "1.00";
  $("#productUserLimit").value = "1";
  $("#productTotalLimit").value = "10";
  $("#productActive").checked = true;
  $("#productFormTitle").textContent = "添加上架商品";
});


$("#openButton").addEventListener("click", () => {
  if (state.busy || state.data.status.is_open) return;
  openConfirmation({
    title: "手动开放今日打卡",
    description: `确认立即开放 ${state.data.status.day} 的打卡？开放后登录用户可正式参与练习与排名。`,
    check: "我确认立即开放今日打卡。",
    path: "/api/admin/open",
    body: {},
  });
});

$("#refreshButton").addEventListener("click", async () => {
  if (state.busy) return;
  setBusy(true);
  try {
    await refresh();
    notify("全部数据已刷新。");
  } catch (err) {
    notify(err.message);
  } finally {
    setBusy(false);
  }
});

$("#cancelConfirmation").addEventListener("click", () => {
  if (!state.busy) $("#confirmationDialog").close();
});

$("#confirmationForm").addEventListener("submit", async (event) => {
  event.preventDefault();
  if (state.busy || !state.action || !$("#confirmed").checked) return;
  const { path, body } = state.action;
  setBusy(true);
  try {
    await api(path, body);
    state.action = null;
    $("#confirmationDialog").close();
    await refresh();
    notify("操作已成功执行。");
  } catch (err) {
    notify(`操作失败：${err.message}`);
  } finally {
    setBusy(false);
  }
});

(async () => {
  try { state.token = sessionStorage.getItem(tokenKey) || ""; } catch {}
  if (!state.token) return;
  setBusy(true);
  try {
    await refresh();
  } catch (err) {
    showLogin();
    $("#loginError").textContent = err.message;
  } finally {
    setBusy(false);
  }
})();

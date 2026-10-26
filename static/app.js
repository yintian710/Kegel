"use strict";

const $ = (selector) => document.querySelector(selector);
const prompts = [
  '再提一组？',
  '最后一组？',
  '三组完成'
];

const state = {
  started: false,
  busy: false,
  status: null,
  mode: null,
  session: null,
  entry: null,
  step: 0,
  readyAt: 0,
  expiresAt: 0,
  poll: null,
  polling: false,
  error: "",
  autoPaused: false,
  currentView: "landing"
};

async function api(path, body) {
  const response = await fetch(path, {
    method: body === undefined ? "GET" : "POST",
    credentials: "same-origin",
    headers: { "Content-Type": "application/json" },
    ...(body === undefined ? {} : { body: JSON.stringify(body) }),
  });
  const data = await response.json().catch(() => { throw new Error("服务器响应无法读取，请稍后再试。"); });
  if (!response.ok || data.ok === false) throw new Error(data.error || `请求失败（${response.status}）`);
  return data;
}

function notify(message) {
  const notice = $("#notice");
  notice.textContent = message;
  notice.hidden = false;
  clearTimeout(notify.timer);
  notify.timer = setTimeout(() => { notice.hidden = true; }, 4000);
}

function resetPractice(message) {
  state.session = null;
  state.mode = null;
  state.step = 0;
  state.readyAt = 0;
  state.expiresAt = 0;
  state.autoPaused = false;
  if (state.status) state.status.session = null;
  if (message && state.started) notify(message);
}

function applySession(session) {
  state.session = session;
  state.step = Math.max(0, Math.min(3, Number(session.step)));
  state.readyAt = Date.now() + Math.max(0, Number(session.wait_seconds) || 0) * 1000;
  state.expiresAt = session.expires_in === null ? 0 : Date.now() + Math.max(0, Number(session.expires_in) || 0) * 1000;
  state.mode = session.eligible ? "server" : !state.status?.user ? "anonymous" : state.status.review ? "review" : "closed";
}

function applyStatus(status) {
  const previousDay = state.status?.day;
  state.status = status;
  if (previousDay && previousDay !== status.day) {
    state.entry = null;
    resetPractice("新的一天开始了，点击页面开始今天的练习。");
  }
  if (status.entry) {
    state.entry = status.entry;
    state.step = 3;
    state.mode = "server";
  } else if (status.session) {
    applySession(status.session);
  } else if (state.session) {
    resetPractice("十分钟未进入下一组，本轮已失效，请从第一组重新开始。");
  }
  if (state.started) render();
}

const visit = api("/api/visit", {}).then((status) => {
  applyStatus(status);
  return status;
}).catch((error) => {
  state.error = error.message;
  return null;
});

function renderLeaderboard() {
  const list = $("#leaderboardList");
  if (!list) return;
  list.replaceChildren();
  const records = state.status?.leaderboard || [];
  const currentUsername = state.status?.user?.username;
  $("#leaderboardTotal").textContent = `已有 ${state.status?.total || 0} 人完成今日打卡`;

  // Rules list
  const rules = $("#rewardRules");
  if (rules) {
    rules.replaceChildren();
    let start = 1;
    for (const tier of state.status?.reward_tiers || []) {
      const item = document.createElement("li");
      const label = document.createElement("span");
      label.className = "tier-range";
      label.textContent = start === tier.through ? `第 ${start} 名` : `第 ${start} - ${tier.through} 名`;
      const val = document.createElement("span");
      val.className = "tier-val";
      val.textContent = `${tier.amount} 积分`;
      item.append(label, val);
      rules.append(item);
      start = tier.through + 1;
    }
    const remaining = document.createElement("li");
    const remLabel = document.createElement("span");
    remLabel.className = "tier-range";
    remLabel.textContent = `第 ${start} 名起`;
    const remVal = document.createElement("span");
    remVal.className = "tier-val";
    remVal.style.color = "var(--text-dim)";
    remVal.textContent = "无积分";
    remaining.append(remLabel, remVal);
    rules.append(remaining);
  }

  // Quota progress bar
  const quota = state.status?.quota;
  if (quota) {
    $("#quotaUsedText").textContent = `每日已用 ${quota.used} / ${quota.limit}`;
    $("#quotaRemainingText").textContent = `剩余 ${quota.remaining}`;
    const pct = quota.limit > 0 ? Math.min(100, Math.round((quota.used / quota.limit) * 100)) : 0;
    $("#quotaBarFill").style.width = `${pct}%`;
  }

  if (!records.length) {
    const row = document.createElement("tr");
    const cell = document.createElement("td");
    cell.colSpan = 3;
    cell.style.textAlign = "center";
    cell.style.color = "var(--text-dim)";
    cell.textContent = "今天的第一份向上，正在路上。";
    row.append(cell);
    list.append(row);
    return;
  }

  for (const record of records) {
    const row = document.createElement("tr");
    if (currentUsername && record.username === currentUsername) {
      row.classList.add("current-user");
    }
    const rankCell = document.createElement("td");
    if (record.rank <= 3) {
      const badge = document.createElement("span");
      badge.className = `rank-badge rank-${record.rank}`;
      badge.textContent = record.rank;
      rankCell.append(badge);
    } else {
      rankCell.textContent = record.rank;
    }

    const userCell = document.createElement("td");
    userCell.textContent = currentUsername && record.username === currentUsername ? `你 (@${record.username})` : `@${record.username}`;

    const amountCell = document.createElement("td");
    amountCell.textContent = `${record.amount}`;

    row.append(rankCell, userCell, amountCell);
    list.append(row);
  }
}

let lastViewType = "landing";
async function switchView(targetView, updateFn) {
  if (lastViewType === targetView) {
    updateFn();
    return;
  }
  lastViewType = targetView;
  const content = $("#stageContent");
  if (!content || matchMedia("(prefers-reduced-motion: reduce)").matches) {
    updateFn();
    return;
  }
  content.classList.add("scene-fading");
  await new Promise((resolve) => setTimeout(resolve, 200));
  updateFn();
  content.classList.remove("scene-fading");
}

function renderResult() {
  const result = $("#result");
  const button = $("#claimButton");
  const pill = $("#statusPill");
  const note = $("#rewardNote");
  const promptWrap = $("#promptWrap");

  if (state.step !== 3) {
    switchView("prompt", () => {
      promptWrap.hidden = false;
      result.hidden = true;
    });
    return;
  }

  switchView("completed", () => {
    promptWrap.hidden = true;
    result.hidden = false;

    const status = state.status;
    button.hidden = true;
    pill.hidden = true;
    note.textContent = "";

    if (state.entry) {
      const entry = state.entry;
      $("#rankNumber").textContent = entry.rank;
      $("#rewardAmount").textContent = entry.amount;

      if (entry.reward_status === "credited") {
        pill.hidden = false;
        pill.className = "status-pill credited";
        pill.textContent = "已记入钱包";
        note.textContent = "今日打卡奖励已成功记入站内积分钱包。";
      } else if (entry.reward_status === "none") {
        pill.hidden = false;
        pill.className = "status-pill";
        pill.textContent = "打卡已记录";
        note.textContent = "已记录今日排名，本名次无站内积分奖励。";
      } else {
        // Unclaimed
        const quota = status?.quota;
        const available = quota && entry.amount <= quota.remaining;
        button.hidden = false;
        button.disabled = state.busy || !available;
        button.textContent = state.busy ? "正在领取…" : available ? "领取站内积分" : quota?.remaining === 0 ? "今日额度已用完" : "剩余额度不足";
        if (!available) {
          note.textContent = quota?.remaining === 0
            ? "今日全站积分额度已用完，当天不能再领取。"
            : `今日剩余 ${quota?.remaining ?? 0} 分，当前奖励 ${entry.amount} 分；整笔额度不足，不能拆分领取。`;
        }
      }
    } else if (state.mode === "closed") {
      $("#completionTitle").innerHTML = '今日练习完成';
      $("#rewardLabel").textContent = "打卡尚未开放，本次仅为本地练习，不计排名。";
      note.textContent = `每日最晚 ${status?.deadline || "22:00"}（北京时间）开放，也可能提前开启。`;
    } else if (state.mode === "review") {
      $("#completionTitle").innerHTML = '今日练习完成';
      $("#rewardLabel").textContent = "今日访问需要管理员确认，暂不计排名。";
      note.textContent = "请联系管理员确认访问记录。批准后刷新页面，开始正式打卡。";
    } else {
      // Anonymous
      $("#completionTitle").innerHTML = '今日练习完成';
      $("#rewardLabel").textContent = "本次为本地练习，登录后可参与每日正式排名。";
      button.hidden = false;
      button.disabled = !status?.oauth_ready;
      button.textContent = status?.oauth_ready ? "LINUX DO 登录参与排名" : "登录暂未配置";
      note.textContent = "登录后按提示完成正式打卡，名次由服务器确认并分配奖励。";
    }

    renderLeaderboard();
  });
}

function exercisePrompt() {
  if (!state.session) return '你今天<span class="prompt-accent">提肛</span>了吗？';
  const remaining = Math.max(0, Math.ceil((state.readyAt - Date.now()) / 1000));
  if (remaining > 0) {
    return ["第一组提肛", "第二组提肛", "第三组提肛"][state.step];
  }
  return prompts[state.step];
}

function renderHint() {
  if (!state.started || state.step === 3) return;
  const remaining = Math.max(0, Math.ceil((state.readyAt - Date.now()) / 1000));
  const hintEl = $("#stageHint");
  const stage = $("#stage");

  if (state.busy) {
    hintEl.textContent = "正在记录，请稍候…";
  } else if (state.autoPaused) {
    hintEl.textContent = "记录未完成，点击页面或按键重试";
  } else if (!state.session) {
    hintEl.textContent = "点击任意位置或按任意键开始";
  } else if (remaining > 0) {
    hintEl.textContent = `轻轻收紧，缓慢放松 · 本组还剩 ${remaining} 秒`;
  } else if (state.step < 2) {
    hintEl.textContent = `点击页面或按任意键，开始第 ${state.step + 2} 组`;
  } else {
    hintEl.textContent = "三组完成，正在确认记录…";
  }

  stage.setAttribute("role", state.session && remaining > 0 ? "region" : "button");
  stage.setAttribute("aria-label", `${state.session ? ["第一组","第二组","第三组"][state.step] : "开始练习"}，${remaining > 0 ? "等待倒计时" : "点击继续"}`);

  const promptEl = $("#prompt");
  const newPrompt = exercisePrompt();
  if (promptEl.innerHTML !== newPrompt) {
    promptEl.innerHTML = newPrompt;
  }
}

function render() {
  if (!state.started) return;
  const status = state.status;
  $("#topbar").hidden = false;
  $("#footer").hidden = false;
  $("#progress").hidden = state.step === 3;
  document.body.dataset.step = String(state.step);

  const dots = document.querySelectorAll("#progress span");
  dots.forEach((dot, index) => dot.classList.toggle("active", index <= state.step));

  $("#accountButton").textContent = status?.user ? `@${status.user.username} · 退出` : "LINUX DO 登录";
  $("#walletLink").textContent = status?.wallet ? `商店 (${status.wallet.balance})` : "商店";

  if (status) {
    $("#openingNote").textContent = status.review && !status.review.approved
      ? "今日访问待管理员确认 · 可以先做本地练习"
      : status.is_open
        ? `今日打卡已开放 · ${status.total} 人完成`
        : `今日尚未开放 · 最晚 ${status.deadline} 北京时间开启`;
    if (status.quota) {
      $("#openingNote").textContent += ` · 今日额度剩余 ${status.quota.remaining} 分`;
    }
  }

  renderHint();
  renderResult();
}

async function pollStatus() {
  if (!state.started || state.busy || state.polling || document.hidden) return;
  state.polling = true;
  try {
    applyStatus(await api("/api/status"));
  } catch (error) {
    $("#openingNote").textContent = `状态更新暂不可用 · ${error.message}`;
  } finally {
    state.polling = false;
  }
}

async function begin() {
  if (!state.status) applyStatus(await api("/api/status"));
  if (state.entry) return;
  const response = await api("/api/session/start", {});
  applySession(response.session);
}

async function finish() {
  if (state.busy || state.polling || state.step !== 2 || Date.now() < state.readyAt) return;
  state.busy = true;
  state.autoPaused = false;
  try {
    const response = await api("/api/session/complete", { token: state.session.token });
    applySession(response.session);
    if (response.entry) state.entry = response.entry;
  } catch (error) {
    state.autoPaused = true;
    notify(error.message);
  } finally {
    state.busy = false;
    render();
  }
}

async function advance() {
  if (state.busy || state.polling || (state.started && state.step === 3)) return;
  if (state.session && state.expiresAt && Date.now() >= state.expiresAt) {
    resetPractice("十分钟未进入下一组，请从第一组重新开始。");
  }
  if (state.step === 2 && Date.now() >= state.readyAt) return finish();

  state.busy = true;
  state.autoPaused = false;
  try {
    if (!state.started) {
      state.started = true;
      state.poll = setInterval(pollStatus, 20000);
      await visit;
      if (state.entry) return;
      if (state.status?.session) applySession(state.status.session);
      else await begin();
      return;
    }
    if (!state.session) {
      await begin();
      return;
    }
    if (Date.now() < state.readyAt) return;
    const response = await api("/api/session/step", { token: state.session.token });
    applySession(response.session);
  } catch (error) {
    notify(error.message);
  } finally {
    state.busy = false;
    render();
  }
}

function login() {
  if (!state.status?.oauth_ready) return notify("LINUX DO 登录暂未配置，请稍后再来。");
  window.location.assign("/auth/linuxdo/start?next=/");
}

$("#claimButton").addEventListener("click", async () => {
  if (!state.entry) return login();
  if (state.busy || state.entry.reward_status !== "unclaimed") return;
  state.busy = true;
  render();
  try {
    const response = await api("/api/claim", {});
    state.entry = response.entry;
    state.status.entry = response.entry;
    state.status.wallet = response.wallet;
    state.status.quota = response.quota;
    notify("恭喜！站内积分已成功到账。");
  } catch (error) {
    notify(`${error.message}`);
  } finally {
    state.busy = false;
    render();
    await pollStatus();
  }
});

$("#accountButton").addEventListener("click", () => {
  if (state.status?.user) window.location.assign("/auth/logout");
  else login();
});

const interactive = "a, button, input, textarea, select, summary, [contenteditable], [data-interactive], #notice";
document.addEventListener("click", (event) => {
  if (event.target.closest(interactive)) return;
  void advance();
});
document.addEventListener("keydown", (event) => {
  if (event.repeat || event.isComposing || event.ctrlKey || event.altKey || event.metaKey || event.shiftKey ||
      ["Tab", "Escape", "Shift", "Control", "Alt", "Meta", "CapsLock", "Fn", "Unidentified"].includes(event.key) ||
      event.target.closest(interactive)) return;
  event.preventDefault();
  void advance();
});

setInterval(() => {
  if (!state.started || state.busy || state.polling || state.step === 3) return;
  if (state.session && state.expiresAt && Date.now() >= state.expiresAt) {
    resetPractice("十分钟未进入下一组，本轮已失效，请从第一组重新开始。");
    render();
    return;
  }
  renderHint();
  if (state.session && state.step === 2 && !state.autoPaused && !document.hidden && Date.now() >= state.readyAt) {
    void finish();
  }
}, 250);

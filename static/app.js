"use strict";

const $ = (selector) => document.querySelector(selector);
const practicePage = document.body.dataset.page === "practice";
if (practicePage) document.documentElement.classList.add("practice-page-root");

const state = {
  started: false,
  busy: false,
  status: null,
  completionKind: null,
  session: null,
  entry: null,
  step: 0,
  readyAt: 0,
  expiresAt: 0,
  poll: null,
  polling: false,
  error: "",
  autoPaused: false,
  showResult: false,
  training: null,
  trainingError: "",
  syncingTraining: false,
  uploadError: "",
};

const textTransitions = new WeakMap();
let displayedView = "landing";
let desiredView = "landing";
let desiredViewUpdate = null;
let viewTransitionRunning = false;
let autoPromptAnimation = null;
let autoPromptToken = null;

const localPractice = practicePage ? (() => {
  const storageName = "local_training_v1";
  let saved;
  try {
    saved = JSON.parse(localStorage.getItem(storageName) || "{}");
  } catch (_error) {
    saved = {};
  }
  let record = saved && typeof saved === "object" ? saved : {};

  function save() {
    try {
      localStorage.setItem(storageName, JSON.stringify(record));
    } catch (_error) {
      // Training remains available when browser storage is unavailable.
    }
  }

  function today() {
    return new Intl.DateTimeFormat("en-CA", { timeZone: "Asia/Shanghai", year: "numeric", month: "2-digit", day: "2-digit" }).format(new Date());
  }

  function view() {
    if (record.day !== today()) record = { day: today(), count: 0, session: record.session, pending: record.pending || [] };
    const session = record.session;
    if (!session || (!session.completed && session.expires_at <= Date.now())) return null;
    return {
      ...session,
      eligible: false,
      wait_seconds: session.completed ? 0 : Math.max(0, (session.ready_at - Date.now()) / 1000),
      expires_in: session.completed ? null : Math.max(0, (session.expires_at - Date.now()) / 1000),
    };
  }

  function status() {
    const session = view();
    return { day: record.day, session };
  }

  function start(selected, userId) {
    const active = view();
    if (active && !active.completed) return { session: active };
    const seconds = selected.intervalSeconds;
    record.session = {
      token: crypto.randomUUID(), mode: selected.mode, repetitions: selected.repetitions,
      round_id: crypto.randomUUID(), owner_id: userId || null, started_at: Date.now(),
      interval_seconds: seconds, min_seconds: seconds, step: 0, completed: false,
      ready_at: Date.now() + seconds * 1000, expires_at: Date.now() + 600000,
    };
    save();
    return { session: view() };
  }

  function current(token) {
    const session = view();
    if (!session || session.token !== token) throw new Error("本轮训练已失效，请重新开始。");
    if (session.wait_seconds > 0) throw new Error("请等待本次倒计时结束。");
    return record.session;
  }

  function step(token) {
    const session = current(token);
    if (session.completed || session.step >= session.repetitions - 1) throw new Error("本轮次数已全部开始，请等待完成。");
    session.step += 1;
    session.token = crypto.randomUUID();
    session.ready_at = Date.now() + session.interval_seconds * 1000;
    session.expires_at = Date.now() + 600000;
    save();
    return { session: view() };
  }

  function complete(token) {
    const session = current(token);
    if (!session.completed) {
      if (session.step !== session.repetitions - 1) throw new Error("请先完成本轮全部训练次数。");
      session.completed = true;
      session.step = session.repetitions;
      session.ended_at = Date.now();
      if (session.round_id && session.started_at) {
        record.pending ||= [];
        record.pending.push({
          round_id: session.round_id, owner_id: session.owner_id,
          started_at: session.started_at, ended_at: session.ended_at,
          repetitions: session.repetitions, interval_seconds: session.interval_seconds, mode: session.mode,
        });
      }
      record.count = (Number(record.count) || 0) + session.repetitions;
      save();
    }
    return { session: view() };
  }

  function reset() {
    record.session = null;
    save();
  }

  function pending(userId, retryRejected = false) {
    return (record.pending || []).filter((item) => (!item.owner_id || item.owner_id === userId) && (retryRejected || !item.error));
  }

  function bindOwner(roundId, userId) {
    const item = record.pending.find((item) => item.round_id === roundId);
    item.owner_id = userId;
    if (record.session?.round_id === roundId) record.session.owner_id = userId;
    save();
  }

  function uploaded(roundId, userId) {
    record.pending = record.pending.filter((item) => item.round_id !== roundId);
    if (record.session?.round_id === roundId) {
      record.session.uploaded_user_id = userId;
      delete record.session.upload_error;
    }
    save();
  }

  function rejected(roundId, message) {
    const item = record.pending.find((item) => item.round_id === roundId);
    item.error = message;
    if (record.session?.round_id === roundId) record.session.upload_error = message;
    save();
  }

  return { status, start, step, complete, reset, pending, bindOwner, uploaded, rejected };
})() : null;

function preferences() {
  const selected = window.PracticePreferences?.get() || {
    mode: "auto",
    repetitions: 10,
    intervalSeconds: 3,
  };
  return practicePage ? selected : { ...selected, mode: "manual", repetitions: 3 };
}

function repetitionCount(session = state.session) {
  const repetitions = Number(session?.repetitions);
  return Number.isInteger(repetitions) && repetitions >= 1 && repetitions <= 20 ? repetitions : 3;
}

function sessionCompleted(session = state.session) {
  return Boolean(session?.completed) || Boolean(session && Number(session.step) >= repetitionCount(session));
}

function isCompletedView() {
  return state.showResult || sessionCompleted();
}

function isAutoSession() {
  return state.session?.mode === "auto";
}

async function api(path, body) {
  const response = await fetch(path, {
    method: body === undefined ? "GET" : "POST",
    credentials: "same-origin",
    headers: { "Content-Type": "application/json" },
    ...(body === undefined ? {} : { body: JSON.stringify(body) }),
  });
  const data = await response.json().catch(() => { throw new Error("服务器响应无法读取，请稍后再试。"); });
  if (!response.ok || data.ok === false) throw Object.assign(new Error(data.error || `请求失败（${response.status}）`), { status: response.status });
  return data;
}

async function refreshTraining(uploadPending = false) {
  try {
    state.training = await api("/api/practice");
    state.trainingError = "";
    if (uploadPending) await syncTraining();
  } catch (error) {
    state.trainingError = error.message;
  }
  if (state.started) render();
}

async function syncTraining(retryRejected = false) {
  if (state.syncingTraining || !state.training?.user) return;
  const userId = state.training.user.id;
  state.syncingTraining = true;
  state.uploadError = "";
  render();
  try {
    for (const item of localPractice.pending(userId, retryRejected)) {
      localPractice.bindOwner(item.round_id, userId);
      const { owner_id, error: previousError, ...body } = item;
      try {
        const result = await api("/api/practice/records", { ...body, expected_user_id: userId });
        localPractice.uploaded(item.round_id, userId);
        state.training = result;
      } catch (error) {
        state.uploadError = error.message;
        if ([400, 403, 409].includes(error.status)) localPractice.rejected(item.round_id, error.message);
        else break;
      }
    }
  } finally {
    const local = localPractice.status().session;
    if (local && local.round_id === state.session?.round_id) state.session = local;
    state.syncingTraining = false;
    render();
  }
}

function notify(message) {
  const notice = $("#notice");
  notice.textContent = message;
  notice.hidden = false;
  clearTimeout(notify.timer);
  notify.timer = setTimeout(() => { notice.hidden = true; }, 4000);
}

function resetPractice(message) {
  if (practicePage) localPractice.reset();
  state.session = null;
  state.completionKind = null;
  state.step = 0;
  state.readyAt = 0;
  state.expiresAt = 0;
  state.autoPaused = false;
  state.showResult = false;
  if (state.status) state.status.session = null;
  if (message && state.started) notify(message);
}

function applySession(session) {
  const sameSession = state.session?.token === session.token;
  const repetitions = repetitionCount(session);
  state.session = session;
  state.step = Math.max(0, Math.min(repetitions, Number(session.step) || 0));
  const readyAt = Date.now() + Math.max(0, Number(session.wait_seconds) || 0) * 1000;
  state.readyAt = sameSession ? Math.min(state.readyAt, readyAt) : readyAt;
  state.expiresAt = session.expires_in === null ? 0 : Date.now() + Math.max(0, Number(session.expires_in) || 0) * 1000;
  state.completionKind = session.eligible ? "server" : !state.status?.user ? "anonymous" : state.status.review ? "review" : "closed";
  state.showResult = sessionCompleted(session);
  if (!sameSession) state.autoPaused = false;
}

function showHomeCompletion() {
  if (practicePage || state.started) return;
  const completedSession = state.status?.session && sessionCompleted(state.status.session)
    ? state.status.session : null;
  if (!state.status?.entry && !completedSession) return;
  state.started = true;
  if (state.status.entry) {
    state.entry = state.status.entry;
    state.completionKind = "server";
  } else {
    applySession(completedSession);
  }
  state.showResult = true;
  if (!state.poll) state.poll = setInterval(pollStatus, 20000);
  render();
}

function applyStatus(status) {
  const previousDay = state.status?.day;
  state.status = status;
  if (!practicePage && status.session && (status.session.mode !== "manual" || status.session.repetitions !== 3)) status.session = null;
  if (previousDay && previousDay !== status.day) {
    state.entry = null;
    resetPractice("新的一天开始了，点击页面开始今天的练习。");
  }
  if (status.entry) state.entry = status.entry;
  if (state.started && status.session && !sessionCompleted(status.session)) {
    applySession(status.session);
  } else if (state.started && state.session && !sessionCompleted()) {
    resetPractice("十分钟未进入下一次，本轮已失效，请从第一次重新开始。");
  }
  if (state.started) render();
}

const visit = (practicePage ? Promise.resolve(localPractice.status()) : api("/api/visit", {})).then((status) => {
  applyStatus(status);
  showHomeCompletion();
  if (practicePage) {
    state.started = true;
    if (status.session) applySession(status.session);
    render();
    void refreshTraining(true);
    state.poll = setInterval(() => { if (!document.hidden) void refreshTraining(); }, 20000);
  }
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

  const rules = $("#rewardRules");
  if (rules) {
    rules.replaceChildren();
    let start = 1;
    for (const tier of state.status?.reward_tiers || []) {
      const item = document.createElement("li");
      const label = document.createElement("span");
      label.className = "tier-range";
      label.textContent = start === tier.through ? `第 ${start} 名` : `第 ${start} - ${tier.through} 名`;
      const value = document.createElement("span");
      value.className = "tier-val";
      value.textContent = `${tier.amount} 积分`;
      item.append(label, value);
      rules.append(item);
      start = tier.through + 1;
    }
    const remaining = document.createElement("li");
    const remainingLabel = document.createElement("span");
    remainingLabel.className = "tier-range";
    remainingLabel.textContent = `第 ${start} 名起`;
    const remainingValue = document.createElement("span");
    remainingValue.className = "tier-val";
    remainingValue.style.color = "var(--text-dim)";
    remainingValue.textContent = "无积分";
    remaining.append(remainingLabel, remainingValue);
    rules.append(remaining);
  }

  const quota = state.status?.quota;
  const quotaUsed = $("#quotaUsedText");
  const quotaRemaining = $("#quotaRemainingText");
  const quotaBar = $("#quotaBarFill");
  if (quota && quotaUsed && quotaRemaining && quotaBar) {
    quotaUsed.textContent = `今日已兑换 ${quota.used} / ${quota.limit} LDC`;
    quotaRemaining.textContent = `剩余 ${quota.remaining} LDC`;
    const limit = Number(quota.limit);
    const percentage = limit > 0 ? Math.min(100, Math.round((Number(quota.used) / limit) * 100)) : 0;
    quotaBar.style.width = `${percentage}%`;
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
    if (currentUsername && record.username === currentUsername) row.classList.add("current-user");
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

function renderPracticeLeaderboard() {
  const list = $("#practiceLeaderboardList");
  if (!list) return;
  list.replaceChildren();
  const records = (practicePage ? state.training?.leaderboard : state.status?.practice_leaderboard) || [];
  $("#practiceLeaderboardTotal").textContent = state.trainingError && practicePage ? "榜单暂不可用" : records.length ? `今日已有 ${records.length} 人上榜` : "今日暂无记录";
  if (!records.length) {
    const row = document.createElement("tr");
    const cell = document.createElement("td");
    cell.colSpan = 3;
    cell.style.textAlign = "center";
    cell.style.color = "var(--text-dim)";
    cell.textContent = practicePage ? "登录后完成训练并上传，即可计入今日训练榜。" : "完成一次自动练习后会显示在这里。";
    row.append(cell);
    list.append(row);
    return;
  }
  const currentUsername = (practicePage ? state.training?.user : state.status?.user)?.username;
  for (const record of records) {
    const row = document.createElement("tr");
    if (currentUsername && record.username === currentUsername) row.classList.add("current-user");
    const rankCell = document.createElement("td");
    rankCell.textContent = record.rank;
    const userCell = document.createElement("td");
    userCell.textContent = currentUsername && record.username === currentUsername ? `你 (@${record.username})` : `@${record.username}`;
    const countCell = document.createElement("td");
    countCell.textContent = `${record.count} 次`;
    row.append(rankCell, userCell, countCell);
    list.append(row);
  }
}

function renderTrainingRecords() {
  const list = $("#trainingRecordsList");
  if (!list) return;
  list.replaceChildren();
  const records = state.training?.records || [];
  if (!records.length) {
    const row = document.createElement("tr");
    const cell = document.createElement("td");
    cell.colSpan = 4;
    cell.textContent = state.training?.user ? "暂无已上传的训练记录。" : "登录后可上传并查看你的训练记录。";
    row.append(cell);
    list.append(row);
    return;
  }
  for (const record of records) {
    const row = document.createElement("tr");
    const values = [record.started_at, record.ended_at].map((time) => new Date(time).toLocaleString("zh-CN", { timeZone: "Asia/Shanghai", hour12: false }));
    values.push(`${record.repetitions} 次`, record.mode === "auto" ? "自动" : "手动");
    for (const value of values) {
      const cell = document.createElement("td");
      cell.textContent = value;
      row.append(cell);
    }
    list.append(row);
  }
}

function wait(milliseconds) {
  return new Promise((resolve) => setTimeout(resolve, milliseconds));
}

function renderAutoPrompt(element, text) {
  if (autoPromptToken === state.session.token) return;
  autoPromptAnimation?.cancel();
  autoPromptToken = state.session.token;
  element.dataset.autoPrompt = "";
  element.classList.remove("practice-text-fading");
  textTransitions.delete(element);
  element.textContent = text;
  const duration = state.session.interval_seconds * 1000;
  autoPromptAnimation = element.animate([
    { opacity: 0, offset: 0 },
    { opacity: 1, offset: 0.5 },
    { opacity: 0, offset: 1 },
  ], { duration, easing: "linear", fill: "both" });
  autoPromptAnimation.currentTime = Math.min(duration, Math.max(0, duration - (state.readyAt - Date.now())));
}

function stopAutoPrompt(element) {
  autoPromptAnimation?.cancel();
  autoPromptAnimation = null;
  autoPromptToken = null;
  delete element.dataset.autoPrompt;
}

async function fadeText(element, hidden) {
  getComputedStyle(element).opacity;
  element.classList.toggle("practice-text-fading", hidden);
  const transitions = element.getAnimations().filter((animation) => animation.transitionProperty === "opacity");
  await Promise.all(transitions.map((animation) => animation.finished.catch(() => {})));
}

function setFadingText(element, text) {
  if (!element) return;
  let transition = textTransitions.get(element);
  if (!transition) {
    if (element.textContent !== text) element.textContent = text;
    transition = { current: text, pending: null, running: false };
    textTransitions.set(element, transition);
    return;
  }
  if (text === transition.current && transition.pending === null) return;
  transition.pending = text;
  if (transition.running) return;
  transition.running = true;
  void (async () => {
    while (transition.pending !== null) {
      if (transition.pending === transition.current) {
        transition.pending = null;
        continue;
      }
      await fadeText(element, true);
      const next = transition.pending;
      transition.pending = null;
      element.textContent = next;
      transition.current = next;
      await fadeText(element, false);
    }
    transition.running = false;
  })();
}

function switchView(targetView, update) {
  desiredView = targetView;
  desiredViewUpdate = update;
  if (viewTransitionRunning) return;
  if (displayedView === desiredView || displayedView === "landing") {
    displayedView = desiredView;
    desiredViewUpdate();
    return;
  }
  const content = $("#stageContent");
  if (!content) {
    displayedView = desiredView;
    desiredViewUpdate();
    return;
  }
  viewTransitionRunning = true;
  void (async () => {
    while (displayedView !== desiredView) {
      content.classList.add("scene-fading");
      await wait(220);
      const viewAtSwap = desiredView;
      desiredViewUpdate();
      displayedView = viewAtSwap;
      content.classList.remove("scene-fading");
      await wait(220);
    }
    viewTransitionRunning = false;
    desiredViewUpdate?.();
  })();
}

function setCompletionSummary(title, reward, rank = "", amount = "") {
  $("#completionTitlePrefix").textContent = title;
  $("#rankNumber").textContent = rank;
  $("#completionTitleSuffix").textContent = rank ? " 位" : "";
  $("#rewardLabelPrefix").textContent = reward;
  $("#rewardAmount").textContent = amount;
  $("#rewardLabelSuffix").textContent = amount ? " 站内积分" : "";
}

function renderResult() {
  const result = $("#result");
  const button = $("#claimButton");
  const pill = $("#statusPill");
  const note = $("#rewardNote");
  const promptWrap = $("#promptWrap");
  const restartButton = $("#restartButton");

  if (!isCompletedView()) {
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
    if (restartButton) restartButton.disabled = state.busy;

    if (practicePage) {
      const user = state.training?.user;
      const uploaded = Boolean(state.session?.uploaded_user_id);
      const wrongUser = Boolean(state.session?.owner_id && user && state.session.owner_id !== user.id);
      const error = state.session?.upload_error || state.uploadError || state.trainingError;
      setCompletionSummary("本轮练习完成", `共完成 ${repetitionCount()} 次${uploaded ? "，已上传并计入训练榜。" : "，尚未计入训练榜。"}`);
      pill.hidden = false;
      pill.className = uploaded ? "status-pill credited" : "status-pill";
      pill.textContent = uploaded ? "训练记录已上传" : !state.session?.round_id ? "旧记录仅存本地" : state.syncingTraining ? "正在上传…" : error ? "上传未成功" : "等待上传";
      const syncButton = $("#syncPracticeButton");
      syncButton.hidden = uploaded || !state.session?.round_id;
      syncButton.disabled = state.syncingTraining || wrongUser;
      syncButton.textContent = user ? "上传训练记录" : "登录后上传";
      note.textContent = !state.session?.round_id ? "旧的本地记录缺少起止时间，无法补传；请重新开始一轮训练。"
        : wrongUser ? "此轮训练属于开始时登录的账号，请切回该账号后上传。"
        : uploaded ? "可在下方查看本轮起止时间和次数；训练不影响每日打卡和积分。"
        : error || "登录后上传起止时间与次数；每轮需在一小时内完成，并在结束后五分钟内提交。";
    } else if (state.entry) {
      const entry = state.entry;
      setCompletionSummary("今日第 ", "本次奖励 ", entry.rank, entry.amount);
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
        button.hidden = false;
        button.disabled = state.busy;
        button.textContent = state.busy ? "正在领取…" : "领取站内积分";
        note.textContent = "签到积分领取不受每日 LDC 兑换额度限制。";
      }
    } else if (state.completionKind === "closed") {
      setCompletionSummary("今日打卡操作完成", "打卡尚未开放，本次操作不计入正式排名。");
      note.textContent = `每日最晚 ${status?.deadline || "22:00"}（北京时间）开放，也可能提前开启。`;
    } else if (state.completionKind === "review") {
      setCompletionSummary("今日练习完成", "今日访问需要管理员确认，暂不计奖励排名。");
      note.textContent = "请联系管理员确认访问记录。批准后刷新页面，开始正式打卡。";
    } else {
      setCompletionSummary("今日练习完成", "本次访客练习已完成，登录后可参与每日正式排名。");
      button.hidden = false;
      button.disabled = !status?.oauth_ready;
      button.textContent = status?.oauth_ready ? "LINUX DO 登录参与排名" : "登录暂未配置";
      note.textContent = "访客练习不会进入练习次数榜；页面不会保存你的身份信息。";
    }

    renderLeaderboard();
    renderPracticeLeaderboard();
  });
}

function exercisePrompt() {
  if (!state.session) {
    if (!state.started) return "你今天提肛了吗？";
    if (practicePage && state.status?.session && !sessionCompleted(state.status.session)) return "继续本轮练习";
    return preferences().mode === "auto" ? "开始自动练习" : "开始第 1 次？";
  }
  const current = Math.min(state.step + 1, repetitionCount());
  return isAutoSession() ? `第 ${current} 次` : `开始第 ${Math.min(current + 1, repetitionCount())} 次？`;
}

function ensureProgress() {
  const progress = $("#progress");
  const count = repetitionCount();
  if (progress.childElementCount === count) return;
  progress.replaceChildren(...Array.from({ length: count }, () => document.createElement("span")));
}

function renderHint() {
  if (!state.started || isCompletedView()) return;
  const remaining = Math.max(0, Math.ceil((state.readyAt - Date.now()) / 1000));
  const stage = $("#stage");
  let hintText;

  if (state.busy) hintText = "正在记录，请稍候…";
  else if (state.autoPaused) hintText = "自动练习已停止，可用下方按钮继续";
  else if (!state.session) hintText = preferences().mode === "auto" ? "点击页面或按任意键，开始自动练习" : "点击页面或按任意键，开始第 1 次";
  else if (remaining > 0) hintText = "轻轻收紧，缓慢放松 · 本次还剩 ";
  else if (isAutoSession() && state.step < repetitionCount() - 1) hintText = "正在自动进入下一次…";
  else if (state.step < repetitionCount() - 1) hintText = `点击页面或按任意键，开始第 ${state.step + 2} 次`;
  else hintText = `${repetitionCount()} 次完成，正在确认记录…`;

  const hintLabel = $("#stageHintText");
  if (hintLabel.textContent !== hintText) hintLabel.textContent = hintText;
  const countdown = remaining > 0 ? `${remaining} 秒` : "";
  const countdownLabel = $("#stageCountdown");
  if (countdownLabel.textContent !== countdown) countdownLabel.textContent = countdown;
  const waiting = Boolean(state.session && (remaining > 0 || isAutoSession()));
  stage.setAttribute("role", waiting ? "region" : "button");
  const actionNumber = state.session ? Math.min(state.step + (waiting ? 1 : 2), repetitionCount()) : 1;
  stage.setAttribute("aria-label", `${waiting ? "正在进行" : "开始"}第 ${actionNumber} 次练习，${waiting ? "等待倒计时" : "点击开始"}`);
  const seconds = Number(state.session?.interval_seconds ?? state.session?.min_seconds ?? state.status?.min_step_seconds) || 2;
  const prompt = $("#prompt");
  if (isAutoSession()) {
    renderAutoPrompt(prompt, exercisePrompt());
  } else {
    stopAutoPrompt(prompt);
    prompt.style.setProperty("--prompt-fade-duration", `${seconds / 2}s`);
    if (!state.session) textTransitions.delete(prompt);
    setFadingText(prompt, exercisePrompt());
  }
}

function render() {
  if (!state.started) return;
  const status = state.status;
  $("#topbar").hidden = false;
  $("#footer").hidden = false;
  $("#progress").hidden = isCompletedView() || !state.session;
  document.body.dataset.step = String(state.step);
  ensureProgress();
  document.querySelectorAll("#progress span").forEach((dot, index) => dot.classList.toggle("active", index <= state.step));

  const user = (practicePage ? state.training : status)?.user;
  $("#accountButton").textContent = user ? `@${user.username} · 退出` : "LINUX DO 登录";
  $("#accountButton").hidden = false;
  $("#walletLink").textContent = status?.wallet ? `商店 (${status.wallet.balance})` : "商店";
  if (practicePage) {
    $("#openingNote").textContent = "训练在本地计时；登录后上传起止时间与次数，独立统计，不影响每日打卡。";
  } else if (status) {
    $("#openingNote").textContent = status.review && !status.review.approved
      ? "今日访问待管理员确认 · 可以先练习"
      : status.is_open
        ? `今日打卡已开放 · ${status.total} 人完成`
        : `今日尚未开放 · 最晚 ${status.deadline} 北京时间开启`;
    if (status.quota) $("#openingNote").textContent += ` · 今日 LDC 兑换额度剩余 ${status.quota.remaining} LDC`;
  }

  const stopButton = $("#autoStopButton");
  if (stopButton) {
    stopButton.hidden = !(isAutoSession() && !sessionCompleted());
    stopButton.textContent = state.autoPaused ? "继续自动练习" : "停止自动练习";
  }
  renderHint();
  renderResult();
  if (practicePage) {
    renderPracticeLeaderboard();
    renderTrainingRecords();
  }
}

async function pollStatus() {
  if (practicePage || !state.started || state.busy || state.polling || document.hidden) return;
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
  if (practicePage && !window.PracticePreferences.validatePracticeInputs()) {
    document.querySelector('#practiceSettings [aria-invalid="true"]')?.focus();
    throw new Error("请先修正练习设置中的提示。");
  }
  if (!state.status) applyStatus(practicePage ? localPractice.status() : await api("/api/status"));
  if (practicePage) {
    state.showResult = false;
    applySession(localPractice.start(preferences(), state.training?.user?.id).session);
    return;
  }
  const selected = preferences();
  const body = { mode: selected.mode, repetitions: selected.repetitions };
  if (selected.mode === "auto") body.interval_seconds = selected.intervalSeconds;
  const response = await api("/api/session/start", body);
  state.showResult = false;
  applySession(response.session);
}

async function completeSession() {
  if (state.busy || state.polling || !state.session || state.step !== repetitionCount() - 1 || Date.now() < state.readyAt) return;
  state.busy = true;
  try {
    const response = practicePage ? localPractice.complete(state.session.token) : await api("/api/session/complete", { token: state.session.token });
    applySession(response.session);
    if (response.entry) state.entry = response.entry;
    applyStatus(practicePage ? localPractice.status() : await api("/api/status"));
  } catch (error) {
    state.autoPaused = isAutoSession();
    notify(error.message);
  } finally {
    state.busy = false;
    render();
  }
  if (practicePage && sessionCompleted()) void refreshTraining(true);
}

async function stepSession() {
  if (state.busy || state.polling || !state.session || Date.now() < state.readyAt) return;
  state.busy = true;
  try {
    const response = practicePage ? localPractice.step(state.session.token) : await api("/api/session/step", { token: state.session.token });
    applySession(response.session);
  } catch (error) {
    state.autoPaused = isAutoSession();
    notify(error.message);
  } finally {
    state.busy = false;
    render();
  }
}

async function advance() {
  if (state.busy || state.polling || isCompletedView()) return;
  if (state.started && !isAutoSession() && textTransitions.get($("#prompt"))?.running) return;
  if (state.session && state.expiresAt && Date.now() >= state.expiresAt) resetPractice("十分钟未进入下一次，请从第一次重新开始。");
  if (state.session && isAutoSession()) return;
  if (state.session && state.step === repetitionCount() - 1 && Date.now() >= state.readyAt) return completeSession();

  state.busy = true;
  try {
    if (!state.started) {
      state.started = true;
      state.poll = setInterval(pollStatus, 20000);
      await visit;
      if (state.status?.session && !sessionCompleted(state.status.session)) {
        applySession(state.status.session);
      }
      else if (state.entry && preferences().mode !== "auto") {
        state.showResult = true;
        state.completionKind = "server";
      } else if (preferences().mode === "auto") await begin();
      return;
    }
    if (!state.session) {
      await begin();
      return;
    }
    if (Date.now() < state.readyAt) return;
    const response = practicePage ? localPractice.step(state.session.token) : await api("/api/session/step", { token: state.session.token });
    applySession(response.session);
  } catch (error) {
    notify(error.message);
  } finally {
    state.busy = false;
    render();
  }
}

function login() {
  if (!(practicePage ? state.training : state.status)?.oauth_ready) return notify("LINUX DO 登录暂未配置，请稍后再来。");
  window.location.assign(`/auth/linuxdo/start?next=${practicePage ? "/practice" : "/"}`);
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
    notify(error.message);
  } finally {
    state.busy = false;
    render();
    await pollStatus();
  }
});

$("#syncPracticeButton")?.addEventListener("click", async () => {
  await refreshTraining();
  if (!state.training?.user) return login();
  await syncTraining(true);
});

$("#restartButton")?.addEventListener("click", async () => {
  if (state.busy) return;
  if (practicePage && preferences().mode === "manual") {
    resetPractice();
    render();
    return;
  }
  state.busy = true;
  try {
    state.session = null;
    state.showResult = false;
    await begin();
  } catch (error) {
    state.showResult = true;
    notify(error.message);
  } finally {
    state.busy = false;
    render();
  }
});

$("#autoStopButton")?.addEventListener("click", () => {
  if (!isAutoSession() || sessionCompleted()) return;
  state.autoPaused = !state.autoPaused;
  render();
});

$("#accountButton").addEventListener("click", () => {
  if ((practicePage ? state.training : state.status)?.user) window.location.assign("/auth/logout");
  else login();
});

const interactive = "a, button, input, textarea, select, summary, [contenteditable], [data-interactive], #notice";
$("#stage").addEventListener("click", (event) => {
  if (event.target.closest(interactive)) return;
  void advance();
});
$("#stage").addEventListener("keydown", (event) => {
  if (event.repeat || event.isComposing || event.ctrlKey || event.altKey || event.metaKey || event.shiftKey ||
      ["Tab", "Escape", "Shift", "Control", "Alt", "Meta", "CapsLock", "Fn", "Unidentified"].includes(event.key) ||
      event.target.closest(interactive)) return;
  event.preventDefault();
  void advance();
});

window.addEventListener("practicepreferenceschange", () => {
  if (state.started) render();
});

setInterval(() => {
  if (!state.started || state.busy || state.polling || isCompletedView()) return;
  if (state.session && state.expiresAt && Date.now() >= state.expiresAt) {
    resetPractice("十分钟未进入下一次，本轮已失效，请从第一次重新开始。");
    render();
    return;
  }
  renderHint();
  if (!state.session || state.autoPaused || document.hidden || Date.now() < state.readyAt) return;
  if (state.step === repetitionCount() - 1) void completeSession();
  else if (isAutoSession()) void stepSession();
}, 250);

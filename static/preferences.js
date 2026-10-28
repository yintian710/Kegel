"use strict";

(() => {
  const STORAGE_KEY = "practice_preferences_v1";
  const REMINDER_KEY = "practice_reminder_last_v1";
  const DEFAULTS = Object.freeze({
    mode: "auto",
    repetitions: 10,
    intervalSeconds: 3,
    hideTigang: false,
    exerciseName: "",
    notifyHour: false,
    notifyHalfHour: false,
  });
  const TEXT_ATTRIBUTES = ["title", "aria-label", "aria-description", "alt", "placeholder", "content"];
  const textSources = new WeakMap();
  const attributeSources = new WeakMap();
  let reminderTimer = 0;
  let observer = null;

  document.documentElement.classList.add("preferences-pending");
  const privacyStyle = document.createElement("style");
  privacyStyle.textContent = "html.preferences-pending body{visibility:hidden}";
  document.head.append(privacyStyle);

  function safeRead() {
    try {
      return JSON.parse(localStorage.getItem(STORAGE_KEY) || "{}");
    } catch (_error) {
      return {};
    }
  }

  function cleanName(value) {
    return Array.from(String(value || "").replace(/[\u0000-\u001f\u007f]/g, "").trim()).slice(0, 24).join("");
  }

  function integerInRange(value, minimum, maximum, fallback) {
    const number = Number(value);
    return Number.isInteger(number) && number >= minimum && number <= maximum ? number : fallback;
  }

  function normalize(candidate) {
    return {
      mode: candidate?.mode === "auto" ? "auto" : candidate?.mode === "manual" ? "manual" : DEFAULTS.mode,
      repetitions: integerInRange(candidate?.repetitions, 1, 20, DEFAULTS.repetitions),
      intervalSeconds: integerInRange(candidate?.intervalSeconds, 2, 5, DEFAULTS.intervalSeconds),
      hideTigang: candidate?.hideTigang === true,
      exerciseName: cleanName(candidate?.exerciseName),
      notifyHour: candidate?.notifyHour === true,
      notifyHalfHour: candidate?.notifyHalfHour === true,
    };
  }

  const saved = safeRead();
  const params = new URLSearchParams(location.search);
  if (params.has("hide_tigang")) saved.hideTigang = params.get("hide_tigang") === "1";
  if (params.has("exercise_name")) saved.exerciseName = params.get("exercise_name");
  let preferences = normalize(saved);

  function persist() {
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(preferences));
    } catch (_error) {
      // The preferences still apply for the current page when storage is unavailable.
    }
  }
  persist();

  function replacement() {
    return preferences.exerciseName || (preferences.hideTigang ? "训练" : "提肛");
  }

  function filtered(value) {
    return String(value).replaceAll("提肛", replacement());
  }

  function canFilterText(node) {
    const parentName = node.parentElement?.tagName;
    return !["SCRIPT", "STYLE", "NOSCRIPT", "TEXTAREA"].includes(parentName);
  }

  function filterTextNode(node, refreshSource = false) {
    if (!canFilterText(node)) return;
    const current = node.nodeValue || "";
    let source = textSources.get(node);
    if (source === undefined || (!refreshSource && current !== filtered(source))) {
      source = current;
      textSources.set(node, source);
    }
    const next = filtered(source);
    if (current !== next) node.nodeValue = next;
  }

  function sourceAttributes(element) {
    let sources = attributeSources.get(element);
    if (!sources) {
      sources = new Map();
      attributeSources.set(element, sources);
    }
    return sources;
  }

  function filterAttribute(element, name, refreshSource = false) {
    if (!element.hasAttribute(name)) return;
    const current = element.getAttribute(name) || "";
    const sources = sourceAttributes(element);
    let source = sources.get(name);
    if (source === undefined || (!refreshSource && current !== filtered(source))) {
      source = current;
      sources.set(name, source);
    }
    const next = filtered(source);
    if (current !== next) element.setAttribute(name, next);
  }

  function carryPreferences(anchor) {
    const rawHref = anchor.getAttribute("href");
    if (!rawHref || rawHref.startsWith("#") || anchor.hasAttribute("download")) return;
    let url;
    try {
      url = new URL(rawHref, location.href);
    } catch (_error) {
      return;
    }
    if (url.origin !== location.origin || !["http:", "https:"].includes(url.protocol)) return;
    if (preferences.hideTigang) url.searchParams.set("hide_tigang", "1");
    else url.searchParams.delete("hide_tigang");
    if (preferences.exerciseName) url.searchParams.set("exercise_name", preferences.exerciseName);
    else url.searchParams.delete("exercise_name");
    const next = `${url.pathname}${url.search}${url.hash}`;
    if (rawHref !== next) anchor.setAttribute("href", next);
  }

  function filterElement(element, refreshSource = false) {
    for (const name of TEXT_ATTRIBUTES) filterAttribute(element, name, refreshSource);
    if (element.matches("a[href]")) carryPreferences(element);
  }

  function filterTree(root, refreshSource = false) {
    if (root.nodeType === Node.TEXT_NODE) {
      filterTextNode(root, refreshSource);
      return;
    }
    if (root.nodeType !== Node.ELEMENT_NODE && root.nodeType !== Node.DOCUMENT_NODE) return;
    if (root.nodeType === Node.ELEMENT_NODE) filterElement(root, refreshSource);
    const walker = document.createTreeWalker(root, NodeFilter.SHOW_ELEMENT | NodeFilter.SHOW_TEXT);
    let node;
    while ((node = walker.nextNode())) {
      if (node.nodeType === Node.TEXT_NODE) filterTextNode(node, refreshSource);
      else filterElement(node, refreshSource);
    }
  }

  function updateAddress() {
    const url = new URL(location.href);
    if (preferences.hideTigang) url.searchParams.set("hide_tigang", "1");
    else url.searchParams.delete("hide_tigang");
    if (preferences.exerciseName) url.searchParams.set("exercise_name", preferences.exerciseName);
    else url.searchParams.delete("exercise_name");
    history.replaceState(history.state, "", `${url.pathname}${url.search}${url.hash}`);
  }

  function emitChange() {
    window.dispatchEvent(new CustomEvent("practicepreferenceschange", { detail: { ...preferences } }));
  }

  function update(next, updateUrl = true) {
    preferences = normalize({ ...preferences, ...next });
    persist();
    if (updateUrl) updateAddress();
    filterTree(document, true);
    syncSettings();
    scheduleReminder();
    emitChange();
  }

  function validatePracticeInputs() {
    const repetitions = document.getElementById("preferenceRepetitions");
    if (!repetitions) return true;
    const interval = document.getElementById("preferenceInterval");
    const auto = document.getElementById("preferenceModeAuto").checked;
    const count = repetitions.valueAsNumber;
    const seconds = interval.valueAsNumber;
    const errors = [
      [repetitions, "preferenceRepetitionsError", count > 20 ? "最高 20 次" :
        Number.isInteger(count) && count >= 1 ? "" : "请输入 1–20 次的整数"],
      [interval, "preferenceIntervalError", !auto || (Number.isInteger(seconds) && seconds >= 2 && seconds <= 5)
        ? "" : "间隔需为 2–5 秒的整数"],
    ];
    for (const [input, errorId, message] of errors) {
      const error = document.getElementById(errorId);
      error.textContent = message;
      error.hidden = !message;
      input.setAttribute("aria-invalid", String(Boolean(message)));
      input.setCustomValidity(message);
    }
    return errors.every(([, , message]) => !message);
  }

  function buildSettings() {
    if (document.getElementById("practicePreferences")) return;
    const mount = document.getElementById("practiceSettings");
    const panel = document.createElement("details");
    panel.id = "practicePreferences";
    panel.className = "practice-preferences";
    panel.dataset.interactive = "";
    panel.innerHTML = `
      <summary aria-label="打开设置">设置</summary>
      <div class="preferences-panel">
        <h2>显示与提醒设置</h2>
        <label class="preference-check"><input id="preferenceHide" type="checkbox" /> 隐藏默认练习称呼</label>
        <label class="preference-field">自定义称呼
          <input id="preferenceName" class="input-text" type="text" maxlength="24" autocomplete="off" placeholder="例如：核心练习" />
        </label>
        <fieldset class="preference-reminders">
          <legend>时间提醒（可多选）</legend>
          <label class="preference-check"><input id="preferenceHour" type="checkbox" /> 每个整点</label>
          <label class="preference-check"><input id="preferenceHalfHour" type="checkbox" /> 每个半点</label>
        </fieldset>
        <button id="preferencePermission" class="btn-secondary" type="button">允许系统通知</button>
        <p id="preferenceNotificationStatus" class="preference-note" role="status"></p>
        <p class="preference-note">提醒只会在本页面保持打开时触发；电脑休眠期间错过的提醒不会补发。</p>
      </div>`;
    document.body.append(panel);
    if (mount) {
      const options = document.createElement("details");
      options.className = "preferences-panel practice-settings-panel";
      options.open = true;
      options.innerHTML = `
        <summary class="practice-settings-summary">
          <span class="practice-settings-title">练习设置</span>
          <span class="practice-settings-toggle" aria-hidden="true"></span>
        </summary>
        <div class="practice-settings-body">
          <p class="preference-note">训练在浏览器本地计时；登录后上传起止时间与次数，计入独立训练榜，不影响每日打卡。</p>
          <fieldset id="preferenceMode" class="preference-mode">
            <legend>练习方式</legend>
            <div class="preference-mode-options">
              <label class="preference-check"><input id="preferenceModeManual" type="radio" name="practiceMode" value="manual" /> 手动</label>
              <label class="preference-check"><input id="preferenceModeAuto" type="radio" name="practiceMode" value="auto" /> 自动</label>
            </div>
          </fieldset>
          <div class="preference-row">
            <label class="preference-field">练习次数（1–20 次）
              <input id="preferenceRepetitions" class="input-text" type="number" inputmode="numeric" min="1" max="20" step="1" aria-describedby="preferenceRepetitionsError" />
              <span id="preferenceRepetitionsError" class="preference-error" role="alert" hidden></span>
            </label>
            <label class="preference-field">间隔秒数（2–5 秒）
              <input id="preferenceInterval" class="input-text" type="number" inputmode="numeric" min="2" max="5" step="1" aria-describedby="preferenceIntervalError" />
              <span id="preferenceIntervalError" class="preference-error" role="alert" hidden></span>
            </label>
          </div>
          <p id="preferenceModeNote" class="preference-note"></p>
        </div>`;
      mount.append(options);
    }

    const change = () => {
      if (mount) validatePracticeInputs();
      const repetitions = document.getElementById("preferenceRepetitions");
      const interval = document.getElementById("preferenceInterval");
      update({
        ...(mount ? {
          mode: document.getElementById("preferenceModeAuto").checked ? "auto" : "manual",
          ...(repetitions.getAttribute("aria-invalid") !== "true" ? { repetitions: repetitions.valueAsNumber } : {}),
          ...(interval.getAttribute("aria-invalid") !== "true" && !interval.disabled ? { intervalSeconds: interval.valueAsNumber } : {}),
        } : {}),
        hideTigang: document.getElementById("preferenceHide").checked,
        exerciseName: document.getElementById("preferenceName").value,
        notifyHour: document.getElementById("preferenceHour").checked,
        notifyHalfHour: document.getElementById("preferenceHalfHour").checked,
      });
    };
    for (const input of panel.querySelectorAll("select, input")) input.addEventListener("change", change);
    for (const input of mount?.querySelectorAll("select, input") || []) input.addEventListener("change", change);
    for (const input of mount?.querySelectorAll('input[type="number"]') || []) input.addEventListener("input", change);
    document.getElementById("preferenceName").addEventListener("input", change);
    document.getElementById("preferencePermission").addEventListener("click", requestNotificationPermission);
    syncSettings();
  }

  function notificationMessage() {
    if (!("Notification" in window)) return "当前浏览器不支持系统通知。你仍可保存提醒时段。";
    if (Notification.permission === "denied") return "系统通知已被拒绝，请在浏览器的网站设置中重新允许。";
    if (Notification.permission === "granted") return "通知权限已允许。页面打开期间会按所选时段提醒。";
    if (preferences.notifyHour || preferences.notifyHalfHour) return "提醒时段已保存，请点击按钮允许通知。";
    return "选择提醒时段后，点击按钮允许通知。";
  }

  function syncSettings() {
    if (!document.getElementById("preferenceHide")) return;
    const mode = document.getElementById("preferenceMode");
    if (mode) {
      document.getElementById("preferenceModeManual").checked = preferences.mode === "manual";
      document.getElementById("preferenceModeAuto").checked = preferences.mode === "auto";
      const repetitions = document.getElementById("preferenceRepetitions");
      const interval = document.getElementById("preferenceInterval");
      if (repetitions.getAttribute("aria-invalid") !== "true") repetitions.value = String(preferences.repetitions);
      if (interval.getAttribute("aria-invalid") !== "true") interval.value = String(preferences.intervalSeconds);
      repetitions.disabled = false;
      interval.disabled = preferences.mode !== "auto";
      document.getElementById("preferenceModeNote").textContent = preferences.mode === "auto"
        ? "自动模式会按所选次数和间隔连续进行，无需点击下一次。"
        : "手动模式按所选次数练习，每次沿用站点设定的原间隔。";
    }
    document.getElementById("preferenceHide").checked = preferences.hideTigang;
    document.getElementById("preferenceName").value = preferences.exerciseName;
    document.getElementById("preferenceHour").checked = preferences.notifyHour;
    document.getElementById("preferenceHalfHour").checked = preferences.notifyHalfHour;
    const button = document.getElementById("preferencePermission");
    button.disabled = !("Notification" in window) || Notification.permission === "denied";
    button.textContent = "Notification" in window && Notification.permission === "granted" ? "通知已允许" : "允许系统通知";
    document.getElementById("preferenceNotificationStatus").textContent = notificationMessage();
  }

  async function requestNotificationPermission() {
    if (!("Notification" in window)) {
      syncSettings();
      return;
    }
    if (Notification.permission === "default") await Notification.requestPermission();
    syncSettings();
    scheduleReminder();
  }

  function nextReminder(now) {
    let nearest = null;
    for (let hourOffset = 0; hourOffset <= 25; hourOffset += 1) {
      const base = new Date(now);
      base.setMinutes(0, 0, 0);
      base.setHours(base.getHours() + hourOffset);
      const candidates = [];
      if (preferences.notifyHour) candidates.push(new Date(base));
      if (preferences.notifyHalfHour) {
        const half = new Date(base);
        half.setMinutes(30, 0, 0);
        candidates.push(half);
      }
      for (const candidate of candidates) {
        if (candidate.getTime() > now.getTime() && (!nearest || candidate < nearest)) nearest = candidate;
      }
      if (nearest) break;
    }
    return nearest;
  }

  function reminderWasSent(timestamp) {
    try {
      if (localStorage.getItem(REMINDER_KEY) === String(timestamp)) return true;
      localStorage.setItem(REMINDER_KEY, String(timestamp));
    } catch (_error) {
      if (reminderWasSent.last === timestamp) return true;
      reminderWasSent.last = timestamp;
    }
    return false;
  }

  function scheduleReminder() {
    clearTimeout(reminderTimer);
    reminderTimer = 0;
    if (!(preferences.notifyHour || preferences.notifyHalfHour)) return;
    const target = nextReminder(new Date());
    if (!target) return;
    reminderTimer = window.setTimeout(() => {
      const lateness = Date.now() - target.getTime();
      if (lateness >= 0 && lateness <= 30000 && "Notification" in window && Notification.permission === "granted" && !reminderWasSent(target.getTime())) {
        const privateTitle = preferences.hideTigang && !preferences.exerciseName ? "活动提醒" : `${replacement()}提醒`;
        new Notification(privateTitle, { body: "到时间了。页面打开期间才会显示这条提醒，请按自己的节奏进行。" });
      }
      scheduleReminder();
    }, Math.max(0, target.getTime() - Date.now()));
  }

  function observeDocument() {
    observer = new MutationObserver((mutations) => {
      for (const mutation of mutations) {
        if (mutation.type === "characterData") filterTextNode(mutation.target);
        else if (mutation.type === "attributes") {
          if (mutation.attributeName === "href") carryPreferences(mutation.target);
          else filterAttribute(mutation.target, mutation.attributeName);
        } else {
          for (const node of mutation.addedNodes) filterTree(node);
        }
      }
    });
    observer.observe(document.documentElement, {
      subtree: true,
      childList: true,
      characterData: true,
      attributes: true,
      attributeFilter: [...TEXT_ATTRIBUTES, "href"],
    });
  }

  function initialize() {
    try {
      filterTree(document);
      buildSettings();
      filterTree(document);
      scheduleReminder();
      window.dispatchEvent(new CustomEvent("practicepreferencesready", { detail: { ...preferences } }));
    } finally {
      document.documentElement.classList.remove("preferences-pending");
    }
  }

  window.PracticePreferences = Object.freeze({
    get: () => ({ ...preferences }),
    update,
    validatePracticeInputs,
  });

  window.addEventListener("storage", (event) => {
    if (event.key !== STORAGE_KEY) return;
    preferences = normalize(safeRead());
    filterTree(document, true);
    syncSettings();
    scheduleReminder();
    emitChange();
  });
  observeDocument();

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", initialize, { once: true });
  else initialize();
})();

<script setup lang="ts">
import { computed, ref } from 'vue'
import {
  applyTheme,
  notificationMessage,
  playFeedbackSound,
  preferences,
  requestNotificationPermission,
  triggerHaptic,
  updatePreferences,
} from '../composables/usePreferences'

const permissionVersion = ref(0)
const notificationStatus = computed(() => {
  void permissionVersion.value
  return notificationMessage()
})
const permissionUnavailable = computed(() => !('Notification' in window) || Notification.permission === 'denied')
const permissionGranted = computed(() => 'Notification' in window && Notification.permission === 'granted')
const detailsEl = ref<HTMLDetailsElement | null>(null)

function save(): void {
  updatePreferences({ ...preferences })
}

function selectTheme(mode: 'light' | 'dark' | 'system'): void {
  preferences.theme = mode
  save()
  applyTheme()
  triggerHaptic()
}

function testSound(): void {
  playFeedbackSound('complete')
  triggerHaptic([20, 40, 20])
}

function setPresetName(name: string): void {
  preferences.exerciseName = name
  save()
  triggerHaptic()
}

function closePanel(): void {
  if (detailsEl.value) {
    detailsEl.value.open = false
  }
}

async function requestPermission(): Promise<void> {
  await requestNotificationPermission()
  permissionVersion.value += 1
  triggerHaptic()
}
</script>

<template>
  <details id="practicePreferences" ref="detailsEl" class="practice-preferences" data-interactive>
    <summary aria-label="打开设置" title="个性化与提醒设置">
      <svg class="pref-gear-icon" viewBox="0 0 24 24" width="20" height="20" stroke="currentColor" stroke-width="2" fill="none" stroke-linecap="round" stroke-linejoin="round">
        <circle cx="12" cy="12" r="3" />
        <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1 0 2.83 2 2 0 0 1-2.83 0l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-2 2 2 2 0 0 1-2-2v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83 0 2 2 0 0 1 0-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1-2-2 2 2 0 0 1 2-2h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 0-2.83 2 2 0 0 1 2.83 0l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 2-2 2 2 0 0 1 2 2v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 0 2 2 0 0 1 0 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 2 2 2 2 0 0 1-2 2h-.09a1.65 1.65 0 0 0-1.51 1z" />
      </svg>
      <span class="pref-btn-label">设置</span>
    </summary>
    <div class="preferences-backdrop" @click.self="closePanel" />
    <div class="preferences-panel">
      <div class="pref-panel-header">
        <div>
          <h2>个性化与环境设置</h2>
          <p class="pref-panel-subtitle">在本地定制你的专属练习体验与隐私选项</p>
        </div>
        <button class="pref-close-btn" type="button" aria-label="关闭" @click="closePanel">✕</button>
      </div>

      <!-- 主题外观选择 -->
      <div class="pref-section">
        <label class="preference-field-title">界面外观</label>
        <div class="theme-selector">
          <button
            type="button"
            class="theme-card"
            :class="{ active: preferences.theme === 'light' }"
            @click="selectTheme('light')"
          >
            <span class="theme-icon">☀️</span>
            <span class="theme-name">浅色</span>
          </button>
          <button
            type="button"
            class="theme-card"
            :class="{ active: preferences.theme === 'dark' }"
            @click="selectTheme('dark')"
          >
            <span class="theme-icon">🌙</span>
            <span class="theme-name">深色</span>
          </button>
          <button
            type="button"
            class="theme-card"
            :class="{ active: preferences.theme === 'system' }"
            @click="selectTheme('system')"
          >
            <span class="theme-icon">💻</span>
            <span class="theme-name">跟随系统</span>
          </button>
        </div>
      </div>

      <!-- 声音与触感反馈 -->
      <div class="pref-section">
        <label class="preference-field-title">反馈与音效</label>
        <div class="pref-switch-row">
          <label class="preference-check">
            <input v-model="preferences.soundEnabled" type="checkbox" @change="save" />
            <span>训练节奏清音提醒</span>
          </label>
          <button class="btn-sound-preview" type="button" title="试听声音" @click="testSound">试听 ♫</button>
        </div>
        <div class="pref-switch-row">
          <label class="preference-check">
            <input v-model="preferences.hapticEnabled" type="checkbox" @change="save" />
            <span>移动端轻微触感振动</span>
          </label>
        </div>
      </div>

      <!-- 显示与隐私称呼 -->
      <div class="pref-section">
        <label class="preference-field-title">隐私与称呼定制</label>
        <label class="preference-check">
          <input v-model="preferences.hideTigang" type="checkbox" @change="save" />
          <span>摸鱼隐蔽：隐藏默认“提肛”称谓</span>
        </label>
        <div class="preference-field" style="margin-top:10px">
          <span style="font-size:12px;color:var(--text-muted)">自定义全站替代词</span>
          <input
            v-model="preferences.exerciseName"
            class="input-text"
            type="text"
            maxlength="24"
            autocomplete="off"
            placeholder="例如：核心训练"
            @input="save"
          />
          <div class="alias-chips">
            <button type="button" class="alias-chip" @click="setPresetName('核心激活')">+ 核心激活</button>
            <button type="button" class="alias-chip" @click="setPresetName('深层呼吸')">+ 深层呼吸</button>
            <button type="button" class="alias-chip" @click="setPresetName('提阳强身')">+ 提阳强身</button>
          </div>
        </div>
      </div>

      <!-- 定时提醒 -->
      <div class="pref-section">
        <fieldset class="preference-reminders">
          <legend>定时提醒（标签页存活有效）</legend>
          <div style="display:flex;gap:18px;margin-top:6px">
            <label class="preference-check">
              <input v-model="preferences.notifyHour" type="checkbox" @change="save" />
              <span>每个整点</span>
            </label>
            <label class="preference-check">
              <input v-model="preferences.notifyHalfHour" type="checkbox" @change="save" />
              <span>每个半点</span>
            </label>
          </div>
        </fieldset>
        <button class="btn-secondary" type="button" style="width:100%;margin-top:8px" :disabled="permissionUnavailable" @click="requestPermission">
          {{ permissionGranted ? '✓ 系统通知已允许' : '允许桌面系统通知' }}
        </button>
        <p class="preference-note" role="status">{{ notificationStatus }}</p>
      </div>

      <div class="pref-footer-note">
        <span>💡 快捷键：打卡或练习中按 <b>空格</b> / <b>回车</b> 即可推进下一次</span>
      </div>
    </div>
  </details>
</template>

<script setup lang="ts">
import {
  notificationMessage,
  preferences,
  requestNotificationPermission,
  updatePreferences,
} from '../composables/usePreferences'

const permissionVersion = ref(0)
const notificationStatus = computed(() => {
  void permissionVersion.value
  return notificationMessage()
})
const permissionUnavailable = computed(() => !('Notification' in window) || Notification.permission === 'denied')
const permissionGranted = computed(() => 'Notification' in window && Notification.permission === 'granted')

function save(): void {
  updatePreferences({ ...preferences })
}

async function requestPermission(): Promise<void> {
  await requestNotificationPermission()
  permissionVersion.value += 1
}
</script>

<template>
  <details id="practicePreferences" class="practice-preferences" data-interactive>
    <summary aria-label="打开设置">设置</summary>
    <div class="preferences-panel">
      <h2>显示与提醒设置</h2>
      <label class="preference-check">
        <input v-model="preferences.hideTigang" type="checkbox" @change="save" />
        隐藏默认练习称呼
      </label>
      <label class="preference-field">
        自定义称呼
        <input
          v-model="preferences.exerciseName"
          class="input-text"
          type="text"
          maxlength="24"
          autocomplete="off"
          placeholder="例如：核心练习"
          @input="save"
        />
      </label>
      <fieldset class="preference-reminders">
        <legend>时间提醒（可多选）</legend>
        <label class="preference-check">
          <input v-model="preferences.notifyHour" type="checkbox" @change="save" />
          每个整点
        </label>
        <label class="preference-check">
          <input v-model="preferences.notifyHalfHour" type="checkbox" @change="save" />
          每个半点
        </label>
      </fieldset>
      <button class="btn-secondary" type="button" :disabled="permissionUnavailable" @click="requestPermission">
        {{ permissionGranted ? '通知已允许' : '允许系统通知' }}
      </button>
      <p class="preference-note" role="status">{{ notificationStatus }}</p>
      <p class="preference-note">提醒只会在本页面保持打开时触发；电脑休眠期间错过的提醒不会补发。</p>
    </div>
  </details>
</template>

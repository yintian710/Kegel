<script setup lang="ts">
import { computed, reactive, ref, watch } from 'vue'
import type { PracticePreferences } from '../composables/useLocalPractice'
import { savePracticePreferences } from '../composables/useLocalPractice'
import { triggerHaptic } from '../composables/usePreferences'

const props = defineProps<{ modelValue: PracticePreferences }>()
const emit = defineEmits<{ 'update:modelValue': [value: PracticePreferences] }>()

const repetitionsInput = ref<HTMLInputElement>()
const intervalInput = ref<HTMLInputElement>()
const draft = reactive({ repetitions: String(props.modelValue.repetitions), interval: String(props.modelValue.intervalSeconds) })
const repetitionsError = computed(() => {
  const count = Number(draft.repetitions)
  return count > 20 ? '最高 20 次' : Number.isInteger(count) && count >= 1 ? '' : '请输入 1–20 次的整数'
})
const intervalError = computed(() => {
  const seconds = Number(draft.interval)
  return Number.isInteger(seconds) && seconds >= 2 && seconds <= 10 ? '' : '时长需为 2–10 秒的整数'
})
const phaseWidths = computed(() => [props.modelValue.liftEnd, props.modelValue.relaxEnd - props.modelValue.liftEnd, 100 - props.modelValue.relaxEnd])
const phaseStyle = computed(() => ({ '--lift-end': `${props.modelValue.liftEnd}%`, '--relax-end': `${props.modelValue.relaxEnd}%` }))
const phaseLabels = computed(() => props.modelValue.phaseNames.map((name, index) => {
  const percent = phaseWidths.value[index]!
  return `${name} ${percent}% · ${(props.modelValue.intervalSeconds * percent / 100).toFixed(2)}s${percent === 0 ? '（已取消）' : ''}`
}))
const phaseAxis = computed(() => Array.from({ length: 6 }, (_, index) => `${Number((props.modelValue.intervalSeconds * index / 5).toFixed(1))}s`))
const activePhases = computed(() => props.modelValue.phaseNames.filter((_, index) => phaseWidths.value[index]! > 0).join('、'))

function commit(patch: Partial<PracticePreferences>): void {
  const next = { ...props.modelValue, ...patch }
  emit('update:modelValue', next)
  savePracticePreferences(next)
  triggerHaptic()
}
function updateNumbers(): void {
  const patch: Partial<PracticePreferences> = {}
  if (!repetitionsError.value) patch.repetitions = Number(draft.repetitions)
  if (!intervalError.value) patch.intervalSeconds = Number(draft.interval)
  if (Object.keys(patch).length) commit(patch)
}
function setRepetitions(count: number): void {
  draft.repetitions = String(count)
  updateNumbers()
}
function setIntervalSec(sec: number): void {
  draft.interval = String(sec)
  updateNumbers()
}
function updateLift(event: Event): void {
  commit({ liftEnd: Math.min(props.modelValue.relaxEnd, Number((event.target as HTMLInputElement).value)) })
}
function updateRelax(event: Event): void {
  commit({ relaxEnd: Math.max(props.modelValue.liftEnd, Number((event.target as HTMLInputElement).value)) })
}
function updatePhase(index: number, event: Event): void {
  const defaults = ['提～', '放松', '休息'] as const
  const names = [...props.modelValue.phaseNames] as [string, string, string]
  names[index] = Array.from((event.target as HTMLInputElement).value.trim()).slice(0, 24).join('') || defaults[index]!
  commit({ phaseNames: names })
}
function validate(): boolean {
  if (repetitionsError.value) repetitionsInput.value?.focus()
  else if (intervalError.value) intervalInput.value?.focus()
  return !repetitionsError.value && !intervalError.value
}
defineExpose({ validate })

watch(() => props.modelValue, value => {
  if (!repetitionsError.value) draft.repetitions = String(value.repetitions)
  if (!intervalError.value) draft.interval = String(value.intervalSeconds)
}, { deep: true })
</script>

<template>
  <details class="preferences-panel practice-settings-panel" open data-interactive>
    <summary class="practice-settings-summary">
      <div style="display:flex;align-items:center;gap:8px">
        <span style="font-size:18px">⚙️</span>
        <span class="practice-settings-title">练习参数定制</span>
      </div>
      <span class="practice-settings-toggle" aria-hidden="true" />
    </summary>
    <div class="practice-settings-body">
      <p class="preference-note" style="margin-top:0">训练在浏览器本地精准计时；登录后上传起止时间与次数，计入独立训练榜，不影响每日打卡。</p>

      <!-- 模式选择药丸按钮 -->
      <fieldset class="preference-mode">
        <legend>练习方式</legend>
        <div class="preference-mode-options segmented-mode-toggle">
          <label class="segmented-option" :class="{ selected: modelValue.mode === 'manual' }">
            <input type="radio" name="practiceMode" value="manual" :checked="modelValue.mode === 'manual'" @change="commit({ mode: 'manual' })">
            <span>🖱️ 手动点击推进</span>
          </label>
          <label class="segmented-option" :class="{ selected: modelValue.mode === 'auto' }">
            <input type="radio" name="practiceMode" value="auto" :checked="modelValue.mode === 'auto'" @change="commit({ mode: 'auto' })">
            <span>⏱️ 自动连贯计时</span>
          </label>
        </div>
      </fieldset>

      <div class="preference-row">
        <label class="preference-field">
          <span>练习次数（1–20 次）</span>
          <input ref="repetitionsInput" v-model="draft.repetitions" class="input-text" type="number" inputmode="numeric" min="1" max="20" step="1" :aria-invalid="Boolean(repetitionsError)" aria-describedby="preferenceRepetitionsError" @input="updateNumbers">
          <span id="preferenceRepetitionsError" class="preference-error" role="alert" :hidden="!repetitionsError">{{ repetitionsError }}</span>
          <div class="quick-chips">
            <button type="button" class="quick-chip" @click="setRepetitions(3)">3次</button>
            <button type="button" class="quick-chip" @click="setRepetitions(5)">5次</button>
            <button type="button" class="quick-chip" @click="setRepetitions(10)">10次</button>
            <button type="button" class="quick-chip" @click="setRepetitions(20)">20次</button>
          </div>
        </label>
        <label class="preference-field">
          <span>每次时长（2–10 秒）</span>
          <input ref="intervalInput" v-model="draft.interval" class="input-text" type="number" inputmode="numeric" min="2" max="10" step="1" :aria-invalid="Boolean(intervalError)" aria-describedby="preferenceIntervalError" @input="updateNumbers">
          <span id="preferenceIntervalError" class="preference-error" role="alert" :hidden="!intervalError">{{ intervalError }}</span>
          <div class="quick-chips">
            <button type="button" class="quick-chip" @click="setIntervalSec(3)">3秒</button>
            <button type="button" class="quick-chip" @click="setIntervalSec(5)">5秒</button>
            <button type="button" class="quick-chip" @click="setIntervalSec(8)">8秒</button>
            <button type="button" class="quick-chip" @click="setIntervalSec(10)">10秒</button>
          </div>
        </label>
      </div>

      <fieldset class="phase-settings">
        <legend>三阶段比例分配</legend>
        <p class="preference-note">拖动两个分界手柄按 1% 调整；设为 0% 可取消该阶段，新设置从下一轮生效。</p>
        <div id="phaseTimeline" class="phase-timeline" :class="{ 'phase-handles-overlap': modelValue.liftEnd === modelValue.relaxEnd }" :style="phaseStyle">
          <div class="phase-track">
            <span class="track-segment seg-lift" :title="phaseLabels[0]" />
            <span class="track-segment seg-relax" :title="phaseLabels[1]" />
            <span class="track-segment seg-rest" :title="phaseLabels[2]" />
          </div>
          <input id="preferenceLiftEnd" type="range" min="0" max="100" step="1" :value="modelValue.liftEnd" :aria-label="`${modelValue.phaseNames[0]}结束位置`" :aria-valuemax="modelValue.relaxEnd" :aria-valuetext="`${modelValue.liftEnd}%，${(modelValue.intervalSeconds * modelValue.liftEnd / 100).toFixed(2)} 秒`" @input="updateLift">
          <input id="preferenceRelaxEnd" type="range" min="0" max="100" step="1" :value="modelValue.relaxEnd" :aria-label="`${modelValue.phaseNames[1]}结束位置`" :aria-valuemin="modelValue.liftEnd" :aria-valuetext="`${modelValue.relaxEnd}%，${(modelValue.intervalSeconds * modelValue.relaxEnd / 100).toFixed(2)} 秒`" @input="updateRelax">
        </div>
        <div class="phase-axis"><span v-for="tick in phaseAxis" :key="tick">{{ tick }}</span></div>
        <div class="phase-labels" aria-live="polite">
          <span v-for="label in phaseLabels" :key="label" class="phase-label-chip">{{ label }}</span>
        </div>
        <div class="phase-name-fields">
          <label v-for="(_, index) in modelValue.phaseNames" :key="index" class="preference-field">
            <span style="font-size:12px;color:var(--text-muted)">第{{ ['一', '二', '三'][index] }}阶段文字</span>
            <input class="input-text" type="text" maxlength="24" :value="modelValue.phaseNames[index]" :placeholder="['提～', '放松', '休息'][index]" autocomplete="off" @change="updatePhase(index, $event)">
          </label>
        </div>
      </fieldset>
      <div class="mode-summary-tip">
        <span>💡 {{ modelValue.mode === 'auto' ? `自动模式：按时长依次 ${activePhases}，连贯完成 ${modelValue.repetitions} 次。` : `手动模式：每次依次 ${activePhases}，完成后点击或空格开始下一次。` }}</span>
      </div>
    </div>
  </details>
</template>

<script setup lang="ts">
import { computed, reactive, ref, watch } from 'vue'
import type { PracticePreferences } from '../composables/useLocalPractice'
import { savePracticePreferences } from '../composables/useLocalPractice'

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
}
function updateNumbers(): void {
  const patch: Partial<PracticePreferences> = {}
  if (!repetitionsError.value) patch.repetitions = Number(draft.repetitions)
  if (!intervalError.value) patch.intervalSeconds = Number(draft.interval)
  if (Object.keys(patch).length) commit(patch)
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
      <span class="practice-settings-title">练习设置</span><span class="practice-settings-toggle" aria-hidden="true" />
    </summary>
    <div class="practice-settings-body">
      <p class="preference-note">训练在浏览器本地计时；登录后上传起止时间与次数，计入独立训练榜，不影响每日打卡。</p>
      <fieldset class="preference-mode">
        <legend>练习方式</legend>
        <div class="preference-mode-options">
          <label class="preference-check"><input type="radio" name="practiceMode" value="manual" :checked="modelValue.mode === 'manual'" @change="commit({ mode: 'manual' })"> 手动</label>
          <label class="preference-check"><input type="radio" name="practiceMode" value="auto" :checked="modelValue.mode === 'auto'" @change="commit({ mode: 'auto' })"> 自动</label>
        </div>
      </fieldset>
      <div class="preference-row">
        <label class="preference-field">练习次数（1–20 次）
          <input ref="repetitionsInput" v-model="draft.repetitions" class="input-text" type="number" inputmode="numeric" min="1" max="20" step="1" :aria-invalid="Boolean(repetitionsError)" aria-describedby="preferenceRepetitionsError" @input="updateNumbers">
          <span id="preferenceRepetitionsError" class="preference-error" role="alert" :hidden="!repetitionsError">{{ repetitionsError }}</span>
        </label>
        <label class="preference-field">每次时长（2–10 秒）
          <input ref="intervalInput" v-model="draft.interval" class="input-text" type="number" inputmode="numeric" min="2" max="10" step="1" :aria-invalid="Boolean(intervalError)" aria-describedby="preferenceIntervalError" @input="updateNumbers">
          <span id="preferenceIntervalError" class="preference-error" role="alert" :hidden="!intervalError">{{ intervalError }}</span>
        </label>
      </div>
      <fieldset class="phase-settings">
        <legend>阶段分配</legend>
        <p class="preference-note">拖动两个分界点，按 1% 调整；设为 0% 可取消该阶段，新设置从下一轮生效。</p>
        <div id="phaseTimeline" class="phase-timeline" :class="{ 'phase-handles-overlap': modelValue.liftEnd === modelValue.relaxEnd }" :style="phaseStyle">
          <div class="phase-track"><span /><span /><span /></div>
          <input id="preferenceLiftEnd" type="range" min="0" max="100" step="1" :value="modelValue.liftEnd" :aria-label="`${modelValue.phaseNames[0]}结束位置`" :aria-valuemax="modelValue.relaxEnd" :aria-valuetext="`${modelValue.liftEnd}%，${(modelValue.intervalSeconds * modelValue.liftEnd / 100).toFixed(2)} 秒`" @input="updateLift">
          <input id="preferenceRelaxEnd" type="range" min="0" max="100" step="1" :value="modelValue.relaxEnd" :aria-label="`${modelValue.phaseNames[1]}结束位置`" :aria-valuemin="modelValue.liftEnd" :aria-valuetext="`${modelValue.relaxEnd}%，${(modelValue.intervalSeconds * modelValue.relaxEnd / 100).toFixed(2)} 秒`" @input="updateRelax">
        </div>
        <div class="phase-axis"><span v-for="tick in phaseAxis" :key="tick">{{ tick }}</span></div>
        <div class="phase-labels" aria-live="polite"><span v-for="label in phaseLabels" :key="label">{{ label }}</span></div>
        <div class="phase-name-fields">
          <label v-for="(_, index) in modelValue.phaseNames" :key="index" class="preference-field">第{{ ['一', '二', '三'][index] }}阶段文字
            <input class="input-text" type="text" maxlength="24" :value="modelValue.phaseNames[index]" :placeholder="['提～', '放松', '休息'][index]" autocomplete="off" @change="updatePhase(index, $event)">
          </label>
        </div>
        <p class="preference-note">每段最多 24 字，留空恢复默认文字；从下一轮生效。</p>
      </fieldset>
      <p class="preference-note">{{ modelValue.mode === 'auto' ? `自动模式按所选时长依次${activePhases}，连续完成本轮。` : `手动模式每次依次${activePhases}，结束后点击开始下一次。` }}</p>
    </div>
  </details>
</template>

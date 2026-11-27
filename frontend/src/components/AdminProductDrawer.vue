<script setup lang="ts">
import { computed, reactive, ref, watch } from 'vue'
import type { Product, SaveProductInput } from '../api'
import AdminModal from './AdminModal.vue'
import { zheText } from './adminFormat'

const props = defineProps<{ open: boolean; product: Product | null; busy: boolean }>()
const emit = defineEmits<{ save: [value: SaveProductInput]; close: [] }>()

const defaults = (): SaveProductInput => ({
  category: 'LDC',
  name: '',
  description: '',
  points_price: 500,
  ldc_amount: '1.00',
  user_daily_limit: 1,
  total_daily_limit: 10,
  is_active: true,
  draw_count: 10,
})
const form = reactive<SaveProductInput>(defaults())

// 限时折扣表单：几折（1–9.9）+ 结束时间（本地时间）
const promoOn = ref(false)
const promoZhe = ref<number | null>(8)
const promoEnd = ref('')
const errorText = ref('')

const durations: Array<{ label: string; seconds: number }> = [
  { label: '1 小时', seconds: 3600 },
  { label: '6 小时', seconds: 6 * 3600 },
  { label: '1 天', seconds: 86400 },
  { label: '3 天', seconds: 3 * 86400 },
  { label: '7 天', seconds: 7 * 86400 },
]
const tickets: Array<{ count: number; label: string }> = [
  { count: 1, label: '单抽券（1 抽）' },
  { count: 10, label: '十连券（10 抽）' },
  { count: 100, label: '百连券（100 抽）' },
]

function toLocalInput(epochSeconds: number): string {
  const date = new Date(epochSeconds * 1000)
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}T${pad(date.getHours())}:${pad(date.getMinutes())}`
}
function setDuration(seconds: number): void {
  promoEnd.value = toLocalInput(Date.now() / 1000 + seconds)
}

const isTicket = computed(() => form.category === 'TICKET')
const promoBp = computed(() => (promoZhe.value === null ? null : Math.round(promoZhe.value * 1000)))
const promoEndSeconds = computed(() => (promoEnd.value ? new Date(promoEnd.value).getTime() / 1000 : null))
const promoPrice = computed(() => {
  if (!promoOn.value || !promoBp.value) return null
  return Math.ceil((Number(form.points_price) * promoBp.value) / 10000)
})
const promoError = computed(() => {
  if (!promoOn.value) return ''
  if (promoBp.value === null || promoBp.value < 1000 || promoBp.value > 9900) return '折扣须在 1–9.9 折之间'
  if (promoEndSeconds.value === null || Number.isNaN(promoEndSeconds.value)) return '请设置折扣结束时间'
  if (promoEndSeconds.value <= Date.now() / 1000) return '结束时间须晚于现在'
  return ''
})

// 每次打开时按当前商品（或空白）重置表单
watch(() => props.open, (open) => {
  if (!open) return
  Object.assign(form, defaults())
  delete form.id
  promoOn.value = false
  promoZhe.value = 8
  promoEnd.value = ''
  errorText.value = ''
  const p = props.product
  if (p) {
    Object.assign(form, {
      id: p.id,
      category: p.category === 'TICKET' ? 'TICKET' : 'LDC',
      name: p.name,
      description: p.description || '',
      points_price: p.points_price,
      ldc_amount: p.ldc_amount || '1.00',
      user_daily_limit: p.user_daily_limit || 0,
      total_daily_limit: p.total_daily_limit || 0,
      is_active: p.is_active,
      draw_count: p.draw_count || 10,
    })
    // 仍在生效的折扣带入表单；已结束的折扣不带入（需要重新设置）
    if (p.promo_active && p.promo_bp && p.promo_ends_at) {
      promoOn.value = true
      promoZhe.value = p.promo_bp / 1000
      promoEnd.value = toLocalInput(p.promo_ends_at)
    }
  } else {
    setDuration(86400)
  }
}, { immediate: true })

watch(promoOn, (on) => {
  if (on && !promoEnd.value) setDuration(86400)
})

function submit(): void {
  if (promoError.value) {
    errorText.value = promoError.value
    return
  }
  errorText.value = ''
  const payload: SaveProductInput = { ...form }
  if (isTicket.value) {
    payload.ldc_amount = '0.00'
    payload.user_daily_limit = 0
    payload.total_daily_limit = 0
  } else {
    delete payload.draw_count
  }
  if (promoOn.value) {
    payload.promo_enabled = true
    payload.promo_discount_bp = promoBp.value as number
    payload.promo_ends_at = promoEndSeconds.value as number
  } else {
    payload.promo_enabled = false
  }
  emit('save', payload)
}
</script>

<template>
  <AdminModal :open="open" side :label="form.id ? '编辑商品' : '上架新商品'" @close="emit('close')">
    <form @submit.prevent="submit">
      <div class="adm-dialog-head">
        <h2>{{ form.id ? `编辑商品 #${form.id}` : '上架新商品' }}</h2>
        <p>{{ isTicket ? '抽卡券：用积分购买，购买后进入背包，可在「称号」页抽卡。' : 'LDC 自动发货商品：用户兑换后系统会调用 Credit 接口发货。' }}</p>
      </div>
      <div class="adm-dialog-body">
        <div class="adm-field">
          <span class="adm-label">商品品类</span>
          <div class="adm-seg" role="radiogroup" aria-label="商品品类">
            <button type="button" role="radio" :aria-checked="!isTicket" :class="{ on: !isTicket }" :disabled="!!form.id" @click="form.category = 'LDC'">LDC 自动发货</button>
            <button type="button" role="radio" :aria-checked="isTicket" :class="{ on: isTicket }" :disabled="!!form.id" @click="form.category = 'TICKET'">抽卡券</button>
          </div>
          <span v-if="form.id" class="help">已创建的商品不能更改品类</span>
        </div>

        <div class="adm-field">
          <label for="p-name">商品名称</label>
          <input id="p-name" v-model.trim="form.name" class="adm-input" maxlength="80" required>
        </div>
        <div class="adm-field">
          <label for="p-desc">商品介绍</label>
          <textarea id="p-desc" v-model.trim="form.description" class="adm-textarea" rows="3" maxlength="500" />
        </div>

        <div v-if="isTicket" class="adm-field">
          <label for="p-draw">券面额</label>
          <select id="p-draw" v-model.number="form.draw_count" class="adm-select">
            <option v-for="t in tickets" :key="t.count" :value="t.count">{{ t.label }}</option>
          </select>
          <span class="help">十连保底 SR，百连保底 SSR</span>
        </div>

        <div class="adm-row2">
          <div class="adm-field">
            <label for="p-price">积分售价</label>
            <input id="p-price" v-model.number="form.points_price" class="adm-input" type="number" min="0" max="100000000" required>
          </div>
          <div v-if="!isTicket" class="adm-field">
            <label for="p-ldc">LDC 发货数量</label>
            <input id="p-ldc" v-model="form.ldc_amount" class="adm-input" type="number" min="0.01" max="10000" step="0.01" required>
          </div>
          <template v-if="!isTicket">
            <div class="adm-field">
              <label for="p-user">单人每日限购</label>
              <input id="p-user" v-model.number="form.user_daily_limit" class="adm-input" type="number" min="0" max="100000">
              <span class="help">0 表示不限</span>
            </div>
            <div class="adm-field">
              <label for="p-total">全站每日限购</label>
              <input id="p-total" v-model.number="form.total_daily_limit" class="adm-input" type="number" min="0" max="100000">
              <span class="help">0 表示不限</span>
            </div>
          </template>
        </div>

        <!-- 限时折扣 -->
        <div class="adm-promo" :class="{ on: promoOn }">
          <label class="adm-switch">
            <input v-model="promoOn" type="checkbox">
            <span class="track" />
            <span><b>限时折扣</b> <span class="help">到点自动结束，恢复原价</span></span>
          </label>
          <template v-if="promoOn">
            <div class="adm-row2" style="margin-top: 12px">
              <div class="adm-field">
                <label for="p-zhe">折扣力度（几折）</label>
                <input id="p-zhe" v-model.number="promoZhe" class="adm-input" type="number" min="1" max="9.9" step="0.1" required>
              </div>
              <div class="adm-field">
                <label for="p-end">结束时间</label>
                <input id="p-end" v-model="promoEnd" class="adm-input" type="datetime-local" required>
              </div>
            </div>
            <div class="adm-chips" style="margin-top: 8px">
              <span class="help" style="align-self: center">倒计时：</span>
              <button v-for="d in durations" :key="d.label" class="adm-chip" type="button" @click="setDuration(d.seconds)">{{ d.label }}</button>
            </div>
            <p class="adm-promo-preview">
              <template v-if="promoPrice !== null && !promoError">
                {{ zheText(promoBp) }}：原价 {{ Number(form.points_price).toLocaleString() }} → <b>{{ promoPrice.toLocaleString() }}</b> 积分；
                用户持有的称号折扣会在此基础上继续叠加。
              </template>
              <template v-else>{{ promoError }}</template>
            </p>
          </template>
        </div>

        <label class="adm-switch">
          <input v-model="form.is_active" type="checkbox">
          <span class="track" />
          <span>在商店中上架展示</span>
        </label>
        <p v-if="errorText" class="adm-err" role="alert">{{ errorText }}</p>
      </div>
      <div class="adm-dialog-foot">
        <button class="adm-btn" type="button" :disabled="busy" @click="emit('close')">取消</button>
        <button class="adm-btn primary" type="submit" :disabled="busy">保存商品</button>
      </div>
    </form>
  </AdminModal>
</template>

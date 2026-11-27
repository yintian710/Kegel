<script setup lang="ts">
import { nextTick, onBeforeUnmount, ref, watch } from 'vue'

// 统一的弹层容器：挂到 body、固定高层级，居中弹窗或右侧抽屉。
// 不使用原生 <dialog>，避免叠放层级依赖浏览器行为。
const props = defineProps<{ open: boolean; label: string; side?: boolean }>()
const emit = defineEmits<{ close: [] }>()

// 多层弹层（如抽屉里再弹确认框）时，只有最上层响应键盘
const stack: symbol[] = (globalThis as { __admModalStack?: symbol[] }).__admModalStack ??= []
const id = Symbol('adm-modal')
const panel = ref<HTMLElement | null>(null)
const layer = ref(10050) // 按打开顺序叠放：后打开的（如抽屉里弹出的确认框）一定在最上面
let previous: HTMLElement | null = null
const FOCUSABLE = 'input:not([type=hidden]):not(:disabled),textarea:not(:disabled),select:not(:disabled),button:not(:disabled),a[href]'

function onKey(event: KeyboardEvent): void {
  if (stack[stack.length - 1] !== id) return
  if (event.key === 'Escape') {
    event.stopPropagation()
    emit('close')
    return
  }
  if (event.key !== 'Tab' || !panel.value) return
  const items = [...panel.value.querySelectorAll<HTMLElement>(FOCUSABLE)]
  if (!items.length) return
  const first = items[0]!
  const last = items[items.length - 1]!
  if (event.shiftKey && document.activeElement === first) {
    event.preventDefault()
    last.focus()
  } else if (!event.shiftKey && document.activeElement === last) {
    event.preventDefault()
    first.focus()
  }
}

function release(): void {
  const index = stack.indexOf(id)
  if (index >= 0) stack.splice(index, 1)
  document.removeEventListener('keydown', onKey, true)
  if (!stack.length) document.body.style.removeProperty('overflow')
}

watch(() => props.open, async (open) => {
  if (open) {
    previous = document.activeElement as HTMLElement | null
    layer.value = 10050 + stack.length
    stack.push(id)
    document.addEventListener('keydown', onKey, true)
    document.body.style.overflow = 'hidden'
    await nextTick()
    const target = panel.value?.querySelector<HTMLElement>('input:not([type=hidden]):not(:disabled),textarea:not(:disabled),select:not(:disabled)')
    ;(target ?? panel.value?.querySelector<HTMLElement>(FOCUSABLE))?.focus()
  } else {
    release()
    previous?.focus?.()
    previous = null
  }
}, { immediate: true })

onBeforeUnmount(release)
</script>

<template>
  <Teleport to="body">
    <Transition name="adm-modal">
      <div v-if="open" class="adm-overlay" :class="{ side }" :style="{ zIndex: layer }" @mousedown.self="emit('close')">
        <div ref="panel" class="adm-panel" role="dialog" aria-modal="true" :aria-label="label">
          <slot />
        </div>
      </div>
    </Transition>
  </Teleport>
</template>

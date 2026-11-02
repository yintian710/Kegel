import { onBeforeUnmount, onMounted } from 'vue'

export interface BodyAttributes {
  class?: string | string[]
  data?: Record<string, string>
  htmlClass?: string | string[]
}

function classNames(value: string | string[] | undefined): string[] {
  if (!value) return []
  return Array.isArray(value) ? value : value.split(/\s+/).filter(Boolean)
}

export function useBodyAttributes(attributes: BodyAttributes): void {
  const bodyClasses = classNames(attributes.class)
  const htmlClasses = classNames(attributes.htmlClass)

  onMounted(() => {
    document.body.classList.add(...bodyClasses)
    document.documentElement.classList.add(...htmlClasses)
    for (const [name, value] of Object.entries(attributes.data ?? {})) document.body.dataset[name] = value
  })

  onBeforeUnmount(() => {
    document.body.classList.remove(...bodyClasses)
    document.documentElement.classList.remove(...htmlClasses)
    for (const name of Object.keys(attributes.data ?? {})) delete document.body.dataset[name]
  })
}

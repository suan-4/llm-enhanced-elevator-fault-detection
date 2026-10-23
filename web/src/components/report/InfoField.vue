<script setup lang="ts">
import { computed } from 'vue'
import { useReportStore } from '@/stores/report'
import { REQUIRED_FIELDS } from '@/domain/validation'
const props = defineProps<{ field: string; label: string; readonly?: boolean }>()
const store = useReportStore()
const required = (key: string) => REQUIRED_FIELDS.some((f) => f.key === key)
const parts = [{ key: 'floors', unit: '层' }, { key: 'stops', unit: '站' }, { key: 'doors', unit: '门' }]
const unit = computed(() => props.field === 'ratedLoad' ? 'kg' : props.field === 'ratedSpeed' ? 'm/s' : '')
const value = computed(() => {
  if (props.field === 'floorsStopsDoors') return parts.map(p => `${store.form[p.key] || '/'} ${p.unit}`).join('　')
  return `${store.form[props.field] || '/'}${unit.value ? ' ' + unit.value : ''}`
})

function numeric(key: string, event: Event, decimal = false): void {
  const input = event.target as HTMLInputElement
  let cleaned = input.value.replace(decimal ? /[^\d.]/g : /[^\d]/g, '')
  if (decimal) cleaned = (cleaned.match(/^\d*\.?\d*/) ?? [''])[0]
  cleaned = cleaned.slice(0, key === 'ratedSpeed' ? 6 : key === 'ratedLoad' ? 5 : 4)
  store.form[key] = cleaned
  if (input.value !== cleaned) input.value = cleaned
}
</script>

<template>
  <span v-if="readonly">{{ value }}</span>
  <div v-else-if="field === 'floorsStopsDoors'" class="floors">
    <label v-for="part in parts" :key="part.key" class="floor-part">
      <input :id="`f-${part.key}`" :value="store.form[part.key]" class="input input-plain floor-input"
        type="number" min="0" inputmode="numeric" placeholder="/" :aria-label="part.unit + '数'"
        @input="numeric(part.key, $event)" />
      <span class="floor-unit">{{ part.unit }}</span>
    </label>
  </div>
  <div v-else-if="unit" class="unit-field">
    <input :id="`f-${field}`" :value="store.form[field]" class="input input-plain unit-input"
      type="number" min="0" :inputmode="field === 'ratedSpeed' ? 'decimal' : 'numeric'"
      placeholder="/" :aria-label="label" @input="numeric(field, $event, field === 'ratedSpeed')" />
    <span class="unit-label">{{ unit }}</span>
  </div>
  <input v-else :id="`f-${field}`" v-model="store.form[field]" class="input input-plain" type="text"
    :aria-label="label" :aria-required="required(field)" :required="required(field)" />
</template>

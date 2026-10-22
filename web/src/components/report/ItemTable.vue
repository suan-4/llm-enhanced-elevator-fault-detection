<script setup lang="ts">
/* 评价结果表：按项目编号的第一段（1.x / 2.x / …）分组，可折叠展开。
   组名按 GB/T 42615-2023 附录 A 的表名展示（见 domain/itemGroups.ts）；
   分组只是视图层行为：数据、评分与导出仍按 66 条平铺，不改变业务口径。 */
import { computed, reactive } from 'vue'
import ItemRow from './ItemRow.vue'
import { itemGroupName } from '@/domain/itemGroups'
import { useReportStore } from '@/stores/report'
import type { JteItem } from '@/types/api'

const store = useReportStore()
const collapsed = reactive<Record<string, boolean>>({})

interface ItemGroup {
  key: string
  name: string
  range: string
  items: JteItem[]
  total: number
  done: number
  unfit: number
}

const groups = computed<ItemGroup[]>(() => {
  const map = new Map<string, ItemGroup>()
  for (const item of store.items) {
    const key = item.no.split('.')[0] || item.no
    let group = map.get(key)
    if (!group) {
      group = { key, name: itemGroupName(key), range: item.no, items: [], total: 0, done: 0, unfit: 0 }
      map.set(key, group)
    }
    group.items.push(item)
    group.range = group.items.length === 1 ? item.no : group.items[0].no + '–' + item.no
    group.total += 1
    const state = store.stateOf(item.no)
    if (state.result) group.done += 1
    if (state.result === '不符合') group.unfit += 1
  }
  return [...map.values()]
})

function toggle(key: string): void {
  collapsed[key] = !collapsed[key]
}

function expandItem(no: string): void {
  const group = groups.value.find(group => group.items.some(item => item.no === no))
  if (group) collapsed[group.key] = false
}

defineExpose({ expandItem })
</script>

<template>
  <table class="items">
    <colgroup>
      <col style="width: 74px" />
      <col />
      <col style="width: 302px" />
    </colgroup>
    <thead>
      <tr>
        <th>项目编号</th>
        <th>项目</th>
        <th>评价结果</th>
      </tr>
    </thead>
    <tbody v-for="group in groups" :key="group.key">
      <tr class="group-row">
        <td colspan="3">
          <button
            class="group-toggle"
            type="button"
            :aria-expanded="!collapsed[group.key]"
            @click="toggle(group.key)"
          >
            <span class="group-caret" :class="{ open: !collapsed[group.key] }">▸</span>
            <span class="group-no">{{ group.key }}</span>
            <span class="group-title">{{ group.name }}</span>
            <span class="group-range">{{ group.range }}</span>
            <span class="group-meta">
              {{ group.total }} 项 · 已评 {{ group.done }} · 不符合 {{ group.unfit }}
            </span>
          </button>
        </td>
      </tr>
      <template v-if="!collapsed[group.key]">
        <ItemRow v-for="item in group.items" :key="item.no" :item="item" />
      </template>
    </tbody>
  </table>
</template>

<style scoped>
.group-row td {
  background: var(--c-head);
  border: 1px solid var(--c-line);
  padding: 0;
}

.group-toggle {
  display: flex;
  align-items: center;
  gap: 9px;
  width: 100%;
  padding: 7px 10px;
  border: 0;
  background: none;
  color: var(--c-text);
  font: inherit;
  text-align: left;
  cursor: pointer;
}

.group-toggle:hover {
  background: var(--c-primary-soft);
}

.group-caret {
  color: var(--c-primary);
  font-size: 11px;
  transition: transform 0.15s;
}

.group-caret.open {
  transform: rotate(90deg);
}

.group-no {
  min-width: 22px;
  height: 20px;
  padding: 0 5px;
  border-radius: 10px;
  background: var(--c-primary);
  color: #fff;
  font-size: 11px;
  font-weight: 700;
  line-height: 20px;
  text-align: center;
  flex: 0 0 auto;
}

.group-title {
  font-family: var(--font-bold);
  font-weight: 700;
  font-size: 13px;
}

.group-range {
  color: var(--c-muted);
  font-size: 11.5px;
}

.group-meta {
  margin-left: auto;
  color: var(--c-secondary);
  font-size: 11.5px;
  white-space: nowrap;
}

@media (max-width: 900px) {
  /* 窄屏卡片式布局：分组头也做成一张独立的窄卡片 */
  .items .group-row td {
    display: block;
    width: auto;
    border: 0;
    padding: 0;
  }

  .group-toggle {
    padding: 10px 12px;
    gap: 7px;
    flex-wrap: wrap;
  }

  .group-range {
    display: none;
  }

  .group-meta {
    font-size: 11px;
  }
}
</style>

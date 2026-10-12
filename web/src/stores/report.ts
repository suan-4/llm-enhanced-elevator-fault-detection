import { defineStore } from 'pinia'
import { computed, reactive, ref } from 'vue'
import * as reportApi from '@/api/report'
import { collectMissing, countItems, createItemState, type ItemState } from '@/domain/validation'
import type { JteItem } from '@/types/api'

/** 抬头信息表默认值：四项必填留空，其余预填「/」 */
function createForm(): Record<string, string> {
  return {
    clientName: '',
    userName: '',
    installSite: '/',
    deviceCategory: '',
    deviceVariety: '/',
    model: '/',
    productNo: '',
    registerNo: '/',
    manufactureDate: '/',
    manufacturer: '/',
    retrofitUnit: '/',
    retrofitDate: '/',
    maintainUnit: '/',
    ratedLoad: '/ kg',
    ratedSpeed: '/ m/s',
    floorsStopsDoors: '/ 层　/ 站　/ 门',
    controlMode: '/',
    instruments:
      '温湿度计、万用表、绝缘电阻仪、转速表、钢卷尺、钢直尺、塞尺、游标卡尺、钳形电流表、照度计、乘运质量测试仪、声级计等',
    basis:
      '1、GB/T 42615-2023《在用电梯安全评估规范》　2、技术服务合同/协议（合同/协议编号：　　　　）',
    suggestion: '/',
    remark: '/',
    assessDate: '/',
  }
}

export const useReportStore = defineStore('report', () => {
  const items = ref<JteItem[]>([])
  const itemsLoading = ref(false)
  const itemsError = ref('')
  const form = ref<Record<string, string>>(createForm())
  const states = reactive<Record<string, ItemState>>({})

  function stateOf(no: string): ItemState {
    if (!states[no]) states[no] = createItemState()
    return states[no]
  }

  async function loadItems(): Promise<void> {
    if (items.value.length) return
    itemsLoading.value = true
    itemsError.value = ''
    try {
      const res = await reportApi.fetchJteItems()
      items.value = res.items
      resetItemStates()
    } catch (err) {
      itemsError.value = err instanceof Error ? err.message : '条目加载失败'
    } finally {
      itemsLoading.value = false
    }
  }

  /** 只重置评价结果，不动抬头信息 */
  function resetItemStates(): void {
    for (const key of Object.keys(states)) delete states[key]
    for (const item of items.value) states[item.no] = createItemState()
  }

  const counters = computed(() => countItems(items.value, stateOf))
  const missing = computed(() => collectMissing(form.value, items.value, stateOf))

  return {
    items,
    itemsLoading,
    itemsError,
    form,
    states,
    counters,
    missing,
    stateOf,
    loadItems,
    resetItemStates,
  }
})

<script setup lang="ts">
/* 左侧可折叠导航：项目进度 + 三个录入锚点（基础信息 / 检测项目填写 / 所生成报告）。
   样式与旧版一致（260px 深色渐变，折叠到 50px）。
   ⚠ 关键点（旧版实测教训）：折叠时 .sidebar 的 width 与 .main 的 margin-left
   必须用同一时长与缓动，否则展开过程中侧边栏会短暂压住正文左列。 */
import { computed } from 'vue'

export interface NavItem {
  key: string
  label: string
}

const props = defineProps<{
  collapsed: boolean
  items: NavItem[]
  active: string
  userName: string
  showExit: boolean
  progress: { done: number; total: number; unfit: number }
}>()

const emit = defineEmits<{
  toggle: []
  navigate: [key: string]
  logout: []
  settings: []
  exitSystem: []
}>()

const percent = computed(() => {
  const { done, total } = props.progress
  if (!total) return 0
  return Math.max(0, Math.min(100, Math.round((done / total) * 100)))
})
</script>

<template>
  <aside class="sidebar" :class="{ collapsed }">
    <button
      class="sidebar-toggle"
      type="button"
      :title="collapsed ? '展开' : '收起'"
      @click="emit('toggle')"
    >
      {{ collapsed ? '▶' : '◀' }}
    </button>

    <div class="sidebar-brand">
      <h1>电梯安全评估</h1>
      <div class="sub">Elevator Safety Assessment</div>
    </div>

    <div v-if="!collapsed" class="progress">
      <div class="progress-title">项目进度</div>
      <div class="progress-track"><i :style="{ width: percent + '%' }" /></div>
      <div class="progress-meta">
        <b>{{ progress.done }}</b>/{{ progress.total }} 项已评 · 不符合 {{ progress.unfit }}
      </div>
    </div>

    <ul class="sidebar-nav">
      <li
        v-for="(item, index) in items"
        :key="item.key"
        :class="{ active: item.key === active }"
        :data-anchor="item.key"
        @click="emit('navigate', item.key)"
      >
        <span class="step-no">{{ index + 1 }}</span>
        <span class="step-label">{{ item.label }}</span>
      </li>
    </ul>

    <div class="sidebar-spacer" />

    <div class="user-bar">
      <span class="u-info">
        <span class="u-name">{{ userName }}</span>
      </span>
      <span class="u-act">
        <button type="button" @click="emit('logout')">注销</button>
        <button v-if="showExit" class="danger" type="button" @click="emit('exitSystem')">
          退出系统
        </button>
      </span>
    </div>

    <div class="sidebar-footer">
      <span>依据 GB/T 42615-2023<br />在用电梯安全评估规范</span>
      <button
        class="footer-gear"
        type="button"
        title="系统设置"
        aria-label="系统设置"
        @click="emit('settings')"
      >
        ⚙
      </button>
    </div>

    <button
      v-if="collapsed"
      class="rail-gear"
      type="button"
      title="系统设置"
      aria-label="系统设置"
      @click="emit('settings')"
    >
      ⚙
    </button>
  </aside>
</template>

<style scoped>
.sidebar {
  width: 260px;
  background: linear-gradient(180deg, #1a2638 0%, #15202f 100%);
  color: #fff;
  position: fixed;
  top: 0;
  left: 0;
  height: 100vh;
  display: flex;
  flex-direction: column;
  padding: 24px 0;
  overflow: hidden;
  transition: width 0.3s ease;
  z-index: 200;
}

.sidebar-toggle {
  position: absolute;
  top: 8px;
  right: 8px;
  width: 28px;
  height: 28px;
  background: rgba(255, 255, 255, 0.07);
  border: 1px solid rgba(255, 255, 255, 0.12);
  border-radius: 6px;
  color: rgba(255, 255, 255, 0.5);
  cursor: pointer;
  font-size: 12px;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: all 0.2s;
}

.sidebar-toggle:hover {
  background: rgba(255, 255, 255, 0.12);
  color: #fff;
}

.sidebar-brand {
  padding: 0 22px 20px;
  border-bottom: 1px solid rgba(255, 255, 255, 0.08);
  margin-bottom: 14px;
}

.sidebar-brand h1 {
  font-size: 15.75px;
  font-weight: 700;
  letter-spacing: 0.04em;
  white-space: nowrap;
}

.sidebar-brand .sub {
  font-size: 9.3px;
  color: rgba(255, 255, 255, 0.4);
  margin-top: 2px;
  white-space: nowrap;
}

/* ── 项目进度 ── */
/* 按现场要求去掉项目进度卡片 */
.progress {
  display: none;
}

.progress {
  margin: 0 14px 16px;
  padding: 12px 12px 11px;
  border-radius: var(--radius-sm);
  background: rgba(255, 255, 255, 0.05);
  border: 1px solid rgba(255, 255, 255, 0.08);
}

.progress-title {
  font-size: 11.5px;
  font-weight: 700;
  color: rgba(255, 255, 255, 0.78);
  letter-spacing: 0.04em;
  margin-bottom: 8px;
}

.progress-track {
  height: 6px;
  border-radius: 3px;
  background: rgba(255, 255, 255, 0.12);
  overflow: hidden;
}

.progress-track i {
  display: block;
  height: 100%;
  border-radius: 3px;
  background: linear-gradient(90deg, #2d8ab5 0%, #4fb3d9 100%);
  transition: width 0.25s ease;
}

.progress-meta {
  margin-top: 7px;
  font-size: 10px;
  color: rgba(255, 255, 255, 0.45);
  white-space: nowrap;
}

.progress-meta b {
  color: rgba(255, 255, 255, 0.82);
  font-weight: 600;
}

/* ── 锚点导航 ── */
.sidebar-nav {
  list-style: none;
  padding: 0 12px;
  margin: 0;
}

.sidebar-nav li {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 11px 14px;
  border-radius: var(--radius-sm);
  cursor: pointer;
  font-size: 12px;
  font-weight: 500;
  color: rgba(255, 255, 255, 0.5);
  transition:
    color 0.2s,
    background-color 0.2s,
    border-color 0.2s;
  border: 1px solid transparent;
  white-space: nowrap;
}

.sidebar-nav li:hover {
  color: rgba(255, 255, 255, 0.8);
  background: rgba(255, 255, 255, 0.04);
}

.sidebar-nav li.active {
  color: #fff;
  background: rgba(255, 255, 255, 0.08);
  border-color: rgba(255, 255, 255, 0.12);
}

.step-no {
  width: 18px;
  height: 18px;
  flex: 0 0 auto;
  border-radius: 50%;
  border: 1px solid rgba(255, 255, 255, 0.25);
  color: rgba(255, 255, 255, 0.55);
  font-size: 10px;
  line-height: 16px;
  text-align: center;
}

.sidebar-nav li.active .step-no {
  border-color: #2d8ab5;
  background: #2d8ab5;
  color: #fff;
  box-shadow: 0 0 10px rgba(45, 138, 181, 0.5);
}

.sidebar-spacer {
  flex: 1;
  min-height: 0;
}

.user-bar {
  padding: 10px 16px;
  border-top: 1px solid rgba(255, 255, 255, 0.08);
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  font-size: 10.5px;
  flex-wrap: wrap;
}

.u-info {
  min-width: 0;
}

.u-name {
  display: block;
  color: rgba(255, 255, 255, 0.85);
  font-weight: 600;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.u-role {
  font-size: 9px;
  color: rgba(255, 255, 255, 0.4);
}

.u-act {
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
}

.user-bar button {
  background: rgba(255, 255, 255, 0.08);
  border: 1px solid rgba(255, 255, 255, 0.14);
  color: rgba(255, 255, 255, 0.8);
  font-size: 9.3px;
  padding: 4px 9px;
  border-radius: 5px;
  cursor: pointer;
  font-family: inherit;
  transition: all 0.2s;
}

.user-bar button:hover {
  background: rgba(255, 255, 255, 0.18);
  color: #fff;
}

.user-bar button.danger {
  color: #ffb4b4;
  border-color: rgba(255, 120, 120, 0.35);
}

.user-bar button.danger:hover {
  background: rgba(220, 80, 80, 0.28);
  color: #fff;
}

.sidebar-footer {
  padding: 10px 22px 0;
  border-top: 1px solid rgba(255, 255, 255, 0.08);
  font-size: 9.3px;
  color: rgba(255, 255, 255, 0.3);
  white-space: nowrap;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}

.footer-gear,
.rail-gear {
  flex: 0 0 auto;
  width: 36px;
  height: 36px;
  border: 1px solid rgba(255, 255, 255, 0.18);
  border-radius: 8px;
  background: rgba(255, 255, 255, 0.08);
  color: rgba(255, 255, 255, 0.85);
  font-size: 20px;
  line-height: 1;
  cursor: pointer;
}

.rail-gear {
  position: absolute;
  left: 50%;
  bottom: 16px;
  transform: translateX(-50%);
  width: 40px;
  height: 40px;
  font-size: 22px;
}

/* ── 折叠态 ── */
.sidebar.collapsed {
  width: 50px;
  padding: 12px 0;
}

.sidebar.collapsed .sidebar-brand h1,
.sidebar.collapsed .sub,
.sidebar.collapsed .progress,
.sidebar.collapsed .user-bar,
.sidebar.collapsed .sidebar-footer {
  display: none;
}

.sidebar.collapsed .sidebar-nav {
  padding: 0 8px;
}

.sidebar.collapsed .sidebar-nav li {
  justify-content: center;
  padding: 10px 0;
  font-size: 0;
  gap: 0;
}

.sidebar.collapsed .step-label {
  display: none;
}

.sidebar.collapsed .step-no {
  width: 20px;
  height: 20px;
  line-height: 18px;
}

.sidebar.collapsed .sidebar-brand {
  padding: 0;
  margin-bottom: 12px;
  border: none;
  text-align: center;
}

.sidebar.collapsed .sidebar-toggle {
  position: static;
  margin: 0 auto;
}

@media (max-width: 900px) {
  .sidebar {
    width: 186px;
    padding: 16px 0;
  }

  .sidebar-brand {
    padding: 0 14px 14px;
  }

  .sidebar-brand h1 {
    font-size: 13.5px;
  }

  .progress {
    margin: 0 8px 12px;
    padding: 10px;
  }

  .sidebar-nav {
    padding: 0 8px;
  }

  .sidebar-nav li {
    padding: 11px 10px;
    font-size: 11.1px;
    gap: 8px;
  }

  .user-bar {
    flex-direction: column;
    align-items: stretch;
    gap: 8px;
    padding: 10px 14px;
  }

  .user-bar button {
    flex: 1 1 calc(50% - 3px);
    min-width: 0;
    padding: 7px 4px;
    font-size: 9.9px;
    white-space: nowrap;
  }

  .sidebar-footer {
    padding: 8px 14px 0;
  }
}
</style>

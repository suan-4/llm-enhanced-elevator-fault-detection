<script setup lang="ts">
/* 启动页：原版前端在进入登录前会显示联合署名与加载动画，
   这里恢复该体验，视觉沿用机构风格（直角、细线、克制配色）。 */
import BrandLockup from './BrandLockup.vue'
</script>

<template>
  <div class="splash">
    <div class="splash-card">
      <BrandLockup size="large" />
      <div class="title">电梯安全评估系统</div>
      <div class="sub">ELEVATOR SAFETY ASSESSMENT SYSTEM</div>
      <div class="spin" aria-label="加载中" />
      <div class="ver">依据 GB/T 42615-2023《在用电梯安全评估规范》</div>
    </div>
  </div>
</template>

<style scoped>
.splash {
  position: fixed;
  inset: 0;
  background: #10365f;
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 90;
}

.splash-card {
  width: min(calc(100vw - 32px), 520px);
  background: #fff;
  border: 1px solid var(--c-line);
  padding: 30px 24px 24px;
  text-align: center;
}

.title {
  margin-top: 20px;
  font-size: 19px;
  font-weight: 700;
  letter-spacing: 0.14em;
  color: var(--c-ink);
}

.sub {
  margin-top: 6px;
  font-size: 11px;
  letter-spacing: 0.12em;
  color: var(--c-muted);
}

.spin {
  width: 22px;
  height: 22px;
  margin: 22px auto 0;
  border: 2px solid var(--c-line);
  border-top-color: var(--c-primary);
  border-radius: 50%;
  animation: spin 0.8s linear infinite;
}

@keyframes spin {
  to {
    transform: rotate(360deg);
  }
}

.ver {
  margin-top: 18px;
  font-size: 11.5px;
  color: var(--c-muted);
}
</style>

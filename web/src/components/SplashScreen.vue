<script setup lang="ts">
/* 启动页：与旧版单文件前端逐值一致。
   字号按旧版 html{font-size:15px} 换算为 px，保证渲染尺寸相同。 */
import BrandLockup from './BrandLockup.vue'
</script>

<template>
  <div class="splash">
    <div class="splash-logo">
      <BrandLockup />
    </div>
    <div class="splash-title">电梯安全评估系统</div>
    <div class="splash-sub">ELEVATOR SAFETY ASSESSMENT SYSTEM</div>
    <div class="splash-spin" />
    <div class="splash-ver">依据 GB/T 42615-2023《在用电梯安全评估规范》</div>
  </div>
</template>

<style scoped>
.splash {
  position: fixed;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  z-index: 2000;
  background: linear-gradient(160deg, #10365f 0%, #1b5e7a 55%, #0d2b47 100%);
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 20px;
}

.splash-logo {
  background: #fff;
  border-radius: 14px;
  padding: 18px 22px;
  box-shadow: 0 12px 36px rgba(0, 0, 0, 0.3);
  width: min(calc(100vw - 32px), 519px);
}

.splash-title {
  color: #fff;
  font-size: 17.4px;
  font-weight: 700;
  letter-spacing: 0.14em;
}

.splash-sub {
  color: rgba(255, 255, 255, 0.55);
  font-size: 9.9px;
  letter-spacing: 0.12em;
  margin-top: -8px;
}

.splash-spin {
  width: 26px;
  height: 26px;
  border: 2.5px solid rgba(255, 255, 255, 0.22);
  border-top-color: #fff;
  border-radius: 50%;
  animation: spin 0.8s linear infinite;
  margin-top: 6px;
}

@keyframes spin {
  to {
    transform: rotate(360deg);
  }
}

.splash-ver {
  position: absolute;
  bottom: 22px;
  color: rgba(255, 255, 255, 0.32);
  font-size: 9.9px;
}
</style>

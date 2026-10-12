<script setup lang="ts">
/* 联合署名：广东省特种设备检测研究院佛山检测院 · 佛山大学
   启动页与登录页共用，保持机构标识一致（原版首页即为此布局）。 */
withDefaults(defineProps<{ size?: 'normal' | 'large' }>(), { size: 'normal' })
</script>

<template>
  <div class="lockup" :class="size">
    <img class="lg-fs" src="/fslogo.png" alt="广东省特种设备检测研究院佛山检测院" />
    <span class="sep" />
    <img class="lg-fosu" src="/fosulogo.png" alt="佛山大学" />
  </div>
</template>

<style scoped>
.lockup {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 16px;
  width: 100%;
}

.lockup img {
  display: block;
  height: auto;
  min-width: 0;
}

.lockup .lg-fs {
  max-width: 62%;
  max-height: 38px;
}

.lockup .lg-fosu {
  max-width: 22%;
  max-height: 34px;
}

.lockup .sep {
  width: 1px;
  height: 26px;
  background: var(--c-line);
  flex: 0 0 auto;
}

.lockup.large .lg-fs {
  max-height: 52px;
}

.lockup.large .lg-fosu {
  max-height: 46px;
}

.lockup.large .sep {
  height: 36px;
}

@media (max-width: 900px) {
  .lockup {
    gap: 12px;
  }

  .lockup .lg-fs {
    max-height: 32px;
  }

  .lockup .lg-fosu {
    max-height: 28px;
  }
}
</style>

<script setup lang="ts">
/* 联合署名：广东省特种设备检测研究院佛山检测院 · 佛山大学
   样式与旧版单文件前端逐值一致（flex 比例 6.8889 : 0.9706）。 */
</script>

<template>
  <div class="logo-lockup">
    <img class="lg-fs" src="/fslogo.png" alt="广东省特种设备检测研究院佛山检测院" />
    <span class="sep" />
    <img class="lg-fosu" src="/fosulogo.png" alt="佛山大学" />
  </div>
</template>

<style scoped>
.logo-lockup {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 18px;
  width: 100%;
}

.logo-lockup img {
  display: block;
  flex: 0 1 0;
  min-width: 0;
  height: auto;
}

.lg-fs {
  flex-grow: 6.8889;
}

.lg-fosu {
  flex-grow: 0.9706;
}

.logo-lockup .sep {
  flex: 0 0 auto;
  align-self: stretch;
  width: 1px;
  background: #d9dee5;
}
</style>

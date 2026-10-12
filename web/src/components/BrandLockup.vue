<script setup lang="ts">
/* 联合署名：广东省特种设备检测研究院佛山检测院 · 佛山大学
   与旧版单文件前端逐值一致（flex 比例 6.8889 : 0.9706）。

   ⚠ 选择器必须写成 `.logo-lockup .lg-fs`：
   `.logo-lockup img { flex: 0 1 0 }` 的特异性是 (0,1,1)，
   若只写 `.lg-fs { flex-grow }` (0,1,0) 会被它压掉，
   flex-grow 退回 0，配合 basis 0 会让 logo 渲染成 0×0 —— 完全看不见。 */
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

.logo-lockup .lg-fs {
  flex-grow: 6.8889;
}

.logo-lockup .lg-fosu {
  flex-grow: 0.9706;
}

.logo-lockup .sep {
  flex: 0 0 auto;
  align-self: stretch;
  width: 1px;
  background: #d9dee5;
}
</style>

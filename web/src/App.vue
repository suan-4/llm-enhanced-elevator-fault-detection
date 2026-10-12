<script setup lang="ts">
import { RouterView } from 'vue-router'
import { useToast } from '@/utils/toast'

const { message } = useToast()
</script>

<template>
  <RouterView />
  <div v-if="message" class="toast">{{ message }}</div>
</template>

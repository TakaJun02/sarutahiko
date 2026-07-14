<script setup>
import { useAppViewport } from './composables/useAppViewport'

useAppViewport()
</script>

<template>
  <RouterView v-slot="{ Component, route }">
    <Transition name="route-shift">
      <component :is="Component" :key="route.name" />
    </Transition>
  </RouterView>
</template>

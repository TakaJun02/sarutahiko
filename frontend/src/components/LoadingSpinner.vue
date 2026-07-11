<script setup>
const props = defineProps({
  text: {
    type: String,
    default: 'お待ちください…',
  },
})

const gradientId = `gemini-spinner-${crypto.randomUUID()}`
</script>

<template>
  <div class="flex items-center gap-4">
    <div class="relative h-8 w-8">
      <svg class="animate-gemini-spinner-container absolute left-0 top-0 h-full w-full overflow-visible" viewBox="0 0 24 24">
        <defs>
          <linearGradient :id="gradientId" x1="0%" y1="0%" x2="100%" y2="100%">
            <stop offset="0%" stop-color="#FF8A65" />
            <stop offset="50%" stop-color="#FFEB3B" />
            <stop offset="100%" stop-color="#69F0AE" />
          </linearGradient>
        </defs>
        <circle cx="12" cy="12" r="11" fill="none" stroke-width="2.5" class="stroke-gray-500" opacity="0"></circle>
        <circle cx="12" cy="12" r="11" fill="none" :stroke="`url(#${gradientId})`" stroke-width="2.5"
                class="animate-gemini-spinner-arc" stroke-linecap="round" stroke-dasharray="69.115"></circle>
      </svg>
      <div class="absolute inset-0 flex items-center justify-center">
        <img src="/app-icon.png" alt="App Icon"
             class="animate-icon-rotate h-5 w-5 rounded-full"
             style="transform-origin: 50% 50%; box-shadow: 0 0 10px rgba(255, 255, 255, 0.4);">
      </div>
    </div>
    <p class="text-base text-gray-200">{{ props.text }}</p>
  </div>
</template>

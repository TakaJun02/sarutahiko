<script setup>
import { computed } from 'vue'

const STEP_THEMES = {
  analyze: ['#B388FF', '#82B1FF', '#80D8FF'],
  retrieve: ['#448AFF', '#40C4FF', '#84FFFF'],
  search: ['#00B8D4', '#64FFDA', '#A7FFEB'],
  web_search: ['#69F0AE', '#B9F6CA', '#FFFF8D'],
  evaluate: ['#FFD180', '#FFAB40', '#FF8A65'],
  generate: ['#FF8A65', '#FFEB3B', '#69F0AE'],
}

const props = defineProps({
  text: {
    type: String,
    default: 'お待ちください…',
  },
  statusStep: {
    type: String,
    default: 'generate',
  },
  mode: {
    type: String,
    default: 'pending',
    validator: (value) => ['pending', 'settled'].includes(value),
  },
})

const gradientId = `aurora-ring-${globalThis.crypto?.randomUUID?.() ?? Math.random().toString(36).slice(2)}`
const innerGradientId = `${gradientId}-inner`

const themeStyle = computed(() => {
  const colors = STEP_THEMES[props.statusStep] || STEP_THEMES.generate
  return {
    '--aurora-stop-0': colors[0],
    '--aurora-stop-50': colors[1],
    '--aurora-stop-100': colors[2],
  }
})

const displayText = computed(() => props.text || 'お待ちください…')
const isPending = computed(() => props.mode === 'pending')
</script>

<template>
  <div
    class="aurora-ring-v5"
    :class="`aurora-ring-v5--${props.mode}`"
    :style="themeStyle"
  >
    <div class="aurora-ring-v5__stage" aria-hidden="true">
      <div class="aurora-ring-v5__ring">
        <svg
          class="aurora-ring-v5__svg aurora-ring-v5__outer-spin"
          viewBox="0 0 24 24"
        >
          <defs>
            <linearGradient :id="gradientId" x1="0%" y1="0%" x2="100%" y2="100%">
              <stop class="aurora-ring-v5__gradient-stop" offset="0%" stop-color="var(--aurora-stop-0)" />
              <stop class="aurora-ring-v5__gradient-stop" offset="50%" stop-color="var(--aurora-stop-50)" />
              <stop class="aurora-ring-v5__gradient-stop" offset="100%" stop-color="var(--aurora-stop-100)" />
            </linearGradient>
          </defs>
          <circle cx="12" cy="12" r="11" fill="none" stroke-width="2.5" class="stroke-gray-500" opacity="0"></circle>
          <circle
            cx="12"
            cy="12"
            r="11"
            fill="none"
            :stroke="`url(#${gradientId})`"
            stroke-width="2.5"
            class="aurora-ring-v5__arc aurora-ring-v5__arc--glow"
            stroke-linecap="round"
            stroke-dasharray="69.115"
          ></circle>
          <circle
            cx="12"
            cy="12"
            r="11"
            fill="none"
            :stroke="`url(#${gradientId})`"
            stroke-width="2.5"
            class="aurora-ring-v5__arc aurora-ring-v5__arc--main"
            stroke-linecap="round"
            stroke-dasharray="69.115"
          ></circle>
        </svg>
        <svg
          class="aurora-ring-v5__svg aurora-ring-v5__inner-spin"
          viewBox="0 0 24 24"
        >
          <defs>
            <linearGradient :id="innerGradientId" x1="0%" y1="0%" x2="100%" y2="100%">
              <stop class="aurora-ring-v5__gradient-stop" offset="0%" stop-color="var(--aurora-stop-0)" />
              <stop class="aurora-ring-v5__gradient-stop" offset="50%" stop-color="var(--aurora-stop-50)" />
              <stop class="aurora-ring-v5__gradient-stop" offset="100%" stop-color="var(--aurora-stop-100)" />
            </linearGradient>
          </defs>
          <circle
            cx="12"
            cy="12"
            r="8.5"
            fill="none"
            :stroke="`url(#${innerGradientId})`"
            stroke-width="1"
            class="aurora-ring-v5__inner-arc"
            stroke-linecap="round"
            stroke-dasharray="12,41.4"
          ></circle>
        </svg>
      </div>
      <div class="aurora-ring-v5__icon-frame">
        <img src="/app-icon.png" alt="App Icon" class="aurora-ring-v5__icon" />
      </div>
    </div>

    <div class="aurora-ring-v5__body">
      <!--
        type="transition": the status text carries an infinite shimmer animation,
        so Vue must watch transitionend (not animationend) to finish leave phases.
        Without this the leave never resolves and the text stays at opacity 0.
      -->
      <Transition name="aurora-ring-v5-status" mode="out-in" type="transition">
        <p v-if="isPending" :key="displayText" class="aurora-ring-v5__status" aria-live="polite">
          {{ displayText }}
        </p>
      </Transition>
      <div v-if="!isPending" class="aurora-ring-v5__settled">
        <slot />
      </div>
    </div>
  </div>
</template>

<style scoped>
.aurora-ring-v5 {
  --aurora-stop-0: #FF8A65;
  --aurora-stop-50: #FFEB3B;
  --aurora-stop-100: #69F0AE;
  --aurora-stage-size: 32px;
  --aurora-icon-size: 20px;
  display: flex;
  min-width: 0;
  align-items: center;
  gap: 1rem;
}

.aurora-ring-v5--settled {
  --aurora-stage-size: 24px;
  --aurora-icon-size: 24px;
  align-items: flex-start;
  gap: 0.75rem;
}

.aurora-ring-v5__stage {
  position: relative;
  display: grid;
  width: var(--aurora-stage-size);
  height: var(--aurora-stage-size);
  flex: 0 0 var(--aurora-stage-size);
  place-items: center;
  transition:
    width 300ms ease-out,
    height 300ms ease-out,
    flex-basis 300ms ease-out;
}

.aurora-ring-v5__ring {
  position: absolute;
  inset: 0;
  opacity: 1;
  pointer-events: none;
  transform: scale(1);
  transform-origin: 50% 50%;
  transition:
    opacity 300ms ease-out,
    transform 300ms ease-out;
}

.aurora-ring-v5--settled .aurora-ring-v5__ring {
  opacity: 0;
  transform: scale(0.85);
}

.aurora-ring-v5__svg {
  position: absolute;
  inset: 0;
  width: 100%;
  height: 100%;
  overflow: visible;
}

.aurora-ring-v5__outer-spin {
  animation: gemini_spinner_rotate 2s linear infinite;
}

.aurora-ring-v5__gradient-stop {
  transition: stop-color 400ms ease;
}

.aurora-ring-v5__arc {
  animation: gemini_spinner_arc_dash 1.5s ease-in-out infinite;
}

.aurora-ring-v5__arc--glow {
  opacity: 0.45;
  filter: blur(2.5px);
}

.aurora-ring-v5__arc--main {
  opacity: 1;
}

.aurora-ring-v5__inner-spin {
  opacity: 0.3;
  transform-origin: 50% 50%;
  animation: aurora_ring_inner_counter_rotate 3s linear infinite;
}

.aurora-ring-v5__inner-arc {
  opacity: 1;
}

.aurora-ring-v5__icon-frame {
  position: relative;
  z-index: 1;
  display: grid;
  width: var(--aurora-icon-size);
  height: var(--aurora-icon-size);
  place-items: center;
  transition:
    width 300ms ease-out,
    height 300ms ease-out;
}

.aurora-ring-v5__icon {
  width: 100%;
  height: 100%;
  border-radius: 9999px;
  animation: icon_kurun_rotate 4s ease-in-out infinite;
  box-shadow: 0 0 10px rgba(255, 255, 255, 0.4);
  transform-origin: 50% 50%;
}

.aurora-ring-v5--settled .aurora-ring-v5__icon {
  animation: none;
}

.aurora-ring-v5__body {
  min-width: 0;
  flex: 1 1 auto;
}

.aurora-ring-v5__status {
  display: inline-block;
  margin: 0;
  background: linear-gradient(90deg, rgba(255, 255, 255, 0.45), #fff, rgba(255, 255, 255, 0.45));
  background-size: 200% 100%;
  background-clip: text;
  color: transparent;
  font-size: 1rem;
  line-height: 2rem;
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
  animation: aurora_ring_status_shimmer 2.2s linear infinite;
}

.aurora-ring-v5__settled {
  min-width: 0;
}

.aurora-ring-v5-status-enter-active,
.aurora-ring-v5-status-leave-active {
  transition:
    opacity 250ms ease,
    transform 250ms ease;
}

.aurora-ring-v5-status-enter-from {
  opacity: 0;
  transform: translate3d(0, 6px, 0);
}

.aurora-ring-v5-status-leave-to {
  opacity: 0;
  transform: translate3d(0, -6px, 0);
}

@keyframes aurora_ring_inner_counter_rotate {
  100% {
    transform: rotate(-360deg);
  }
}

@keyframes aurora_ring_status_shimmer {
  0% {
    background-position: 200% 50%;
  }
  100% {
    background-position: -200% 50%;
  }
}

@media (prefers-reduced-motion: reduce) {
  .aurora-ring-v5__stage,
  .aurora-ring-v5__icon-frame,
  .aurora-ring-v5__icon {
    transition: none !important;
  }

  .aurora-ring-v5__ring {
    transition: opacity 300ms ease-out !important;
  }

  .aurora-ring-v5--settled .aurora-ring-v5__ring {
    opacity: 0;
    transform: none;
  }

  .aurora-ring-v5__outer-spin,
  .aurora-ring-v5__inner-spin,
  .aurora-ring-v5__arc,
  .aurora-ring-v5__status,
  .aurora-ring-v5__icon {
    animation: none !important;
  }

  .aurora-ring-v5__arc {
    stroke-dasharray: 52, 68 !important;
    stroke-dashoffset: 0 !important;
  }

  .aurora-ring-v5__status {
    background: none;
    color: rgba(255, 255, 255, 0.8);
    -webkit-text-fill-color: rgba(255, 255, 255, 0.8);
  }

  .aurora-ring-v5-status-enter-active,
  .aurora-ring-v5-status-leave-active {
    transition: opacity 150ms ease !important;
  }

  .aurora-ring-v5-status-enter-from,
  .aurora-ring-v5-status-leave-to {
    opacity: 0;
    transform: none;
  }
}
</style>

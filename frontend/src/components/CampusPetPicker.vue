<script setup>
import { nextTick, onMounted, ref } from 'vue'

import { CAMPUS_PET_FORMS } from '../utils/campusPet'
import CampusPetSvg from './CampusPetSvg.vue'

const props = defineProps({
  currentForm: {
    type: String,
    default: null,
  },
  showHint: {
    type: Boolean,
    default: false,
  },
})

const emit = defineEmits(['select', 'cancel'])
const firstOptionRef = ref(null)

function onKeydown(event) {
  if (event.key === 'Escape') {
    event.preventDefault()
    emit('cancel')
  }
}

function setFirstOptionRef(element, index) {
  if (index === 0) {
    firstOptionRef.value = element
  }
}

onMounted(() => {
  nextTick(() => firstOptionRef.value?.focus({ preventScroll: true }))
})
</script>

<template>
  <div class="campus-pet-host campus-pet-picker-host">
    <section
      class="campus-pet-picker"
      role="group"
      aria-label="キャンパスペットを呼び出す"
      @keydown="onKeydown"
    >
      <header class="campus-pet-picker__head">
        <svg class="campus-pet-picker__smoke-mark" viewBox="0 0 24 24" aria-hidden="true">
          <path d="M7.4 14.2c-1.8 0-3.1-1-3.1-2.4 0-1.5 1.4-2.5 3.2-2.5 0.4-2.3 2.4-3.8 5-3.8 2.8 0 4.8 1.8 5 4.3 1.4 0.2 2.4 1.1 2.4 2.3 0 1.4-1.3 2.2-3 2.2H7.4z" fill="currentColor" opacity="0.42" />
          <path d="M8 17.2h7.8" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" opacity="0.42" />
        </svg>
        <h3 class="campus-pet-picker__title">どの仲間を呼ぶ？</h3>
      </header>
      <div class="campus-pet-picker__stage">
        <button
          v-for="(form, index) in CAMPUS_PET_FORMS"
          :key="form.id"
          :ref="(element) => setFirstOptionRef(element, index)"
          type="button"
          class="campus-pet-picker__option"
          :class="{ 'campus-pet-picker__option--current': form.id === currentForm }"
          :data-form="form.id"
          :style="`--i: ${index}`"
          :aria-current="form.id === currentForm ? 'true' : undefined"
          @click="emit('select', form.id)"
        >
          <span v-if="form.rare" class="campus-pet-picker__rare" aria-hidden="true">★</span>
          <span class="campus-pet-picker__figure">
            <CampusPetSvg :form="form.id" state="idle" />
          </span>
          <span class="campus-pet-picker__name">{{ form.name }}</span>
        </button>
      </div>
      <div class="campus-pet-picker__foot">
        <p v-if="showHint" class="campus-pet-picker__hint">指でつまんで、好きな場所に置けるよ</p>
        <button type="button" class="campus-pet-picker__cancel" @click="emit('cancel')">今はやめておく</button>
      </div>
    </section>
  </div>
</template>

<style scoped>
.campus-pet-picker-host {
  display: contents;
}

.campus-pet-picker {
  width: min(48rem, calc(100% - 2rem));
  margin: 0 auto 0.625rem;
  padding: 0.625rem 0.75rem 0.5rem;
  border: 1px solid var(--color-edge);
  border-left: 2px solid var(--color-signal);
  border-radius: var(--radius-lg);
  background: var(--color-panel);
  animation: campus_pet_picker_rise 240ms var(--ease-expressive) both;
}

.campus-pet-picker__head {
  display: flex;
  align-items: center;
  gap: 0.4rem;
}

.campus-pet-picker__smoke-mark {
  width: 1rem;
  height: 1rem;
  flex: 0 0 auto;
  color: var(--color-signal-soft);
}

.campus-pet-picker__title {
  margin: 0;
  color: var(--color-text);
  font-size: 0.8125rem;
  font-weight: 650;
  line-height: 1.4;
}

.campus-pet-picker__stage {
  position: relative;
  display: flex;
  align-items: flex-end;
  justify-content: center;
  gap: 0.125rem;
  margin-top: 0.375rem;
  padding: 0.375rem 0.25rem 0;
}

.campus-pet-picker__stage::after {
  position: absolute;
  right: 0.5rem;
  bottom: 1.125rem;
  left: 0.5rem;
  border-top: 1px solid var(--color-edge);
  content: "";
  opacity: 0.7;
}

.campus-pet-picker__option {
  position: relative;
  z-index: 1;
  display: grid;
  flex: 1 1 0;
  max-width: 4rem;
  min-width: 2.75rem;
  justify-items: center;
  gap: 0.125rem;
  padding: 0.25rem 0 0.125rem;
  border: 0;
  background: transparent;
  animation: campus_pet_picker_pop 340ms var(--ease-expressive) both;
  animation-delay: calc(var(--i, 0) * 55ms);
}

.campus-pet-picker__figure {
  position: relative;
  width: 100%;
  max-width: 3.5rem;
  aspect-ratio: 1;
  transition: transform var(--motion-fast) var(--ease-expressive);
}

.campus-pet-picker__figure::before {
  position: absolute;
  bottom: -1px;
  left: 50%;
  width: 82%;
  height: 12px;
  border-radius: 50%;
  background: radial-gradient(closest-side, rgba(255, 118, 87, 0.3), transparent);
  content: "";
  opacity: 0;
  transform: translateX(-50%);
  transition: opacity var(--motion-fast) var(--ease-standard);
}

.campus-pet-picker__figure::after {
  position: absolute;
  inset: 8%;
  border-radius: 50%;
  background: var(--pet-paper);
  content: "";
  opacity: 0;
  animation: campus_pet_picker_puff 340ms var(--ease-expressive) both;
  animation-delay: calc(var(--i, 0) * 55ms);
}

.campus-pet-picker__figure .campus-pet {
  position: relative;
  z-index: 1;
}

.campus-pet-picker__option:hover .campus-pet-picker__figure,
.campus-pet-picker__option:focus-visible .campus-pet-picker__figure {
  transform: translateY(-3px);
}

.campus-pet-picker__option:hover .campus-pet-picker__figure::before,
.campus-pet-picker__option:focus-visible .campus-pet-picker__figure::before {
  opacity: 1;
}

.campus-pet-picker__option:active .campus-pet-picker__figure {
  transform: translateY(-1px) scale(0.96);
}

.campus-pet-picker__name {
  color: var(--color-text-dim);
  font-size: 0.625rem;
  line-height: 1.6;
  transition: color var(--motion-fast) var(--ease-standard);
}

.campus-pet-picker__option:hover .campus-pet-picker__name,
.campus-pet-picker__option:focus-visible .campus-pet-picker__name {
  color: var(--color-text);
}

.campus-pet-picker__option--current .campus-pet-picker__name {
  color: var(--color-signal);
}

.campus-pet-picker__option--current .campus-pet-picker__figure::before {
  opacity: 0.55;
}

.campus-pet-picker__rare {
  position: absolute;
  top: -0.125rem;
  right: 12%;
  z-index: 2;
  color: var(--pet-aurora-bridge, #ffc46b);
  font-size: 0.625rem;
  line-height: 1;
  animation: campus_pet_picker_twinkle 2.4s var(--ease-standard) infinite;
}

.campus-pet-picker__foot {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 0.5rem;
  margin-top: 0.125rem;
}

.campus-pet-picker__hint {
  margin: 0;
  color: var(--color-text-dim);
  font-size: 0.6875rem;
  line-height: 1.5;
}

.campus-pet-picker__cancel {
  min-height: 2.25rem;
  flex: 0 0 auto;
  margin-left: auto;
  padding: 0 0.75rem;
  border: 0;
  border-radius: 9999px;
  background: transparent;
  color: var(--color-text-dim);
  font-size: 0.75rem;
  white-space: nowrap;
  transition:
    background-color var(--motion-fast) var(--ease-standard),
    color var(--motion-fast) var(--ease-standard);
}

.campus-pet-picker__cancel:hover,
.campus-pet-picker__cancel:focus-visible {
  background: var(--fill-hover, rgba(244, 243, 237, 0.055));
  color: var(--color-text-muted);
}

@keyframes campus_pet_picker_rise {
  from { opacity: 0; transform: translate3d(0, 8px, 0); }
  to { opacity: 1; transform: translate3d(0, 0, 0); }
}

@keyframes campus_pet_picker_pop {
  0% { opacity: 0; transform: translate3d(0, 6px, 0) scale(0.6); }
  62% { opacity: 1; transform: translate3d(0, -1px, 0) scale(1.06); }
  100% { opacity: 1; transform: translate3d(0, 0, 0) scale(1); }
}

@keyframes campus_pet_picker_puff {
  0% { opacity: 0.32; transform: scale(0.45); }
  100% { opacity: 0; transform: scale(1.25); }
}

@keyframes campus_pet_picker_twinkle {
  0%, 100% { opacity: 0.55; }
  50% { opacity: 1; }
}

@media (prefers-reduced-motion: reduce) {
  .campus-pet-picker,
  .campus-pet-picker__option,
  .campus-pet-picker__figure::after,
  .campus-pet-picker__rare {
    animation: none !important;
  }

  .campus-pet-picker__figure,
  .campus-pet-picker__name,
  .campus-pet-picker__cancel {
    transition: none !important;
  }

  .campus-pet-picker__option:hover .campus-pet-picker__figure,
  .campus-pet-picker__option:active .campus-pet-picker__figure {
    transform: none;
  }
}
</style>

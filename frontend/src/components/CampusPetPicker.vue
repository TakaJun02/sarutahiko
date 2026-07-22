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
      <p class="campus-pet-picker__kicker">どの仲間を呼ぶ？</p>
      <div class="campus-pet-picker__apparition">
        <span class="campus-pet-picker__halo" aria-hidden="true"></span>
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
        <span class="campus-pet-picker__ground" aria-hidden="true"></span>
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
  position: relative;
  width: min(48rem, calc(100% - 2rem));
  margin: 0 auto 0.625rem;
  padding: 0.375rem 0 0;
  border: 0;
  background: transparent;
  text-align: center;
}

.campus-pet-picker__kicker {
  margin: 0 0 0.25rem;
  color: var(--color-text-muted);
  font-size: 0.75rem;
  font-weight: 620;
  letter-spacing: 0.14em;
  animation: campus_pet_picker_fade 240ms var(--ease-standard) 60ms both;
}

.campus-pet-picker__apparition {
  position: relative;
  padding: 0.875rem 0.25rem 0;
}

.campus-pet-picker__halo {
  position: absolute;
  bottom: 0.875rem;
  left: 50%;
  width: 16rem;
  height: 8.5rem;
  border-radius: 50%;
  background: radial-gradient(closest-side, rgba(244, 243, 237, 0.1), rgba(244, 243, 237, 0.04) 56%, transparent 74%);
  transform: translateX(-50%);
  animation: campus_pet_halo_bloom 460ms var(--ease-expressive) both;
  pointer-events: none;
}

.campus-pet-picker__stage {
  position: relative;
  z-index: 1;
  display: flex;
  align-items: flex-end;
  justify-content: center;
  gap: 0.125rem;
}

.campus-pet-picker__ground {
  position: absolute;
  right: 6%;
  bottom: 1.375rem;
  left: 6%;
  height: 0.625rem;
  background: radial-gradient(50% 100% at 50% 50%, rgba(244, 243, 237, 0.13), transparent 78%);
  animation: campus_pet_ground_sweep 360ms var(--ease-expressive) 120ms both;
  pointer-events: none;
}

.campus-pet-picker__option {
  position: relative;
  z-index: 2;
  display: grid;
  flex: 1 1 0;
  max-width: 4.25rem;
  min-width: 2.75rem;
  justify-items: center;
  gap: 0.125rem;
  padding: 0.25rem 0 0.125rem;
  border: 0;
  background: transparent;
  animation: campus_pet_picker_pop 380ms var(--ease-expressive) both;
  animation-delay: calc(180ms + var(--i, 0) * 70ms);
}

.campus-pet-picker__figure {
  position: relative;
  width: 100%;
  max-width: 3.75rem;
  aspect-ratio: 1;
  transition: transform var(--motion-fast) var(--ease-expressive);
}

.campus-pet-picker__figure::before {
  position: absolute;
  bottom: -1px;
  left: 50%;
  width: 84%;
  height: 12px;
  border-radius: 50%;
  background: radial-gradient(closest-side, rgba(255, 118, 87, 0.32), transparent);
  content: "";
  opacity: 0;
  transform: translateX(-50%);
  transition: opacity var(--motion-fast) var(--ease-standard);
}

.campus-pet-picker__figure::after {
  position: absolute;
  inset: 4%;
  border-radius: 50%;
  background: var(--pet-paper);
  content: "";
  opacity: 0;
  animation: campus_pet_picker_puff 420ms var(--ease-expressive) both;
  animation-delay: calc(180ms + var(--i, 0) * 70ms);
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
  right: 10%;
  z-index: 3;
  color: var(--pet-aurora-bridge, #ffc46b);
  font-size: 0.625rem;
  line-height: 1;
  animation: campus_pet_picker_twinkle 2.4s var(--ease-standard) infinite;
}

.campus-pet-picker__foot {
  display: flex;
  flex-direction: column;
  align-items: center;
  margin-top: 0.375rem;
  animation: campus_pet_picker_fade 260ms var(--ease-standard) 700ms both;
}

.campus-pet-picker__hint {
  margin: 0;
  color: var(--color-text-dim);
  font-size: 0.6875rem;
  line-height: 1.5;
}

.campus-pet-picker__cancel {
  min-height: 2.25rem;
  padding: 0 0.875rem;
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

@keyframes campus_pet_picker_fade {
  from { opacity: 0; }
  to { opacity: 1; }
}

@keyframes campus_pet_halo_bloom {
  0% { opacity: 0; transform: translateX(-50%) scale(0.72); }
  100% { opacity: 1; transform: translateX(-50%) scale(1); }
}

@keyframes campus_pet_ground_sweep {
  0% { opacity: 0; transform: scaleX(0.3); }
  100% { opacity: 1; transform: scaleX(1); }
}

@keyframes campus_pet_picker_pop {
  0% { opacity: 0; transform: translate3d(0, 8px, 0) scale(0.55); }
  62% { opacity: 1; transform: translate3d(0, -2px, 0) scale(1.07); }
  100% { opacity: 1; transform: translate3d(0, 0, 0) scale(1); }
}

@keyframes campus_pet_picker_puff {
  0% { opacity: 0.38; transform: scale(0.4); }
  100% { opacity: 0; transform: scale(1.3); }
}

@keyframes campus_pet_picker_twinkle {
  0%, 100% { opacity: 0.55; }
  50% { opacity: 1; }
}

@media (prefers-reduced-motion: reduce) {
  .campus-pet-picker__kicker,
  .campus-pet-picker__halo,
  .campus-pet-picker__ground,
  .campus-pet-picker__option,
  .campus-pet-picker__figure::after,
  .campus-pet-picker__rare,
  .campus-pet-picker__foot {
    animation: campus_pet_picker_fade 220ms ease-out both !important;
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

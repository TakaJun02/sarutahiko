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
      <span class="campus-pet-picker__dot" aria-hidden="true"></span>
      <h3 class="campus-pet-picker__title">どの仲間を呼び出す？</h3>
    </header>
    <p v-if="showHint" class="campus-pet-picker__hint">チャットの邪魔はしないよ。指でつまんで好きな場所に置ける。</p>
    <div class="campus-pet-picker__grid">
      <button
        v-for="(form, index) in CAMPUS_PET_FORMS"
        :key="form.id"
        :ref="(element) => setFirstOptionRef(element, index)"
        type="button"
        class="campus-pet-picker__option"
        :class="{
          'campus-pet-picker__option--rare': form.rare,
          'campus-pet-picker__option--current': form.id === currentForm,
        }"
        :data-form="form.id"
        :aria-current="form.id === currentForm ? 'true' : undefined"
        @click="emit('select', form.id)"
      >
        <span v-if="form.rare" class="campus-pet-picker__rare" aria-hidden="true">★</span>
        <span class="campus-pet-picker__thumb">
          <CampusPetSvg :form="form.id" state="idle" />
        </span>
        <span class="campus-pet-picker__name">{{ form.name }}</span>
      </button>
    </div>
    <div class="campus-pet-picker__foot">
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
  padding: 0.75rem 0.875rem 0.625rem;
  border: 1px solid var(--color-edge);
  border-left: 2px solid var(--color-signal);
  border-radius: var(--radius-lg);
  background: var(--color-panel);
}

.campus-pet-picker__head {
  display: flex;
  align-items: center;
  gap: 0.5rem;
}

.campus-pet-picker__dot {
  width: 0.375rem;
  height: 0.375rem;
  flex: 0 0 auto;
  border-radius: 9999px;
  background: var(--color-signal);
}

.campus-pet-picker__title {
  margin: 0;
  color: var(--color-text);
  font-size: 0.8125rem;
  font-weight: 650;
  line-height: 1.4;
}

.campus-pet-picker__hint {
  margin: 0.25rem 0 0 0.875rem;
  color: var(--color-text-dim);
  font-size: 0.75rem;
  line-height: 1.5;
}

.campus-pet-picker__grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 0.375rem;
  margin-top: 0.625rem;
}

.campus-pet-picker__option {
  position: relative;
  display: grid;
  justify-items: center;
  gap: 0.25rem;
  min-height: 5.25rem;
  padding: 0.5rem 0.25rem 0.375rem;
  border: 1px solid var(--color-edge);
  border-radius: var(--radius-md);
  background: transparent;
  transition:
    border-color var(--motion-fast) var(--ease-standard),
    background-color var(--motion-fast) var(--ease-standard),
    transform var(--motion-fast) var(--ease-standard);
}

.campus-pet-picker__option:hover,
.campus-pet-picker__option:focus-visible {
  border-color: var(--color-edge-strong);
  background: var(--fill-hover, rgba(244, 243, 237, 0.055));
}

.campus-pet-picker__option:active {
  transform: scale(0.97);
}

.campus-pet-picker__option--current {
  border-color: rgba(255, 118, 87, 0.34);
}

.campus-pet-picker__option--current::after {
  position: absolute;
  top: 0.375rem;
  left: 0.375rem;
  width: 0.375rem;
  height: 0.375rem;
  border-radius: 9999px;
  background: var(--color-signal);
  content: "";
}

.campus-pet-picker__thumb {
  width: 3rem;
  height: 3rem;
  pointer-events: none;
}

.campus-pet-picker__thumb .campus-pet {
  width: 100%;
  height: 100%;
}

.campus-pet-picker__name {
  color: var(--color-text-muted);
  font-size: 0.6875rem;
  line-height: 1.2;
}

.campus-pet-picker__rare {
  position: absolute;
  top: 0.25rem;
  right: 0.375rem;
  color: var(--pet-aurora-bridge, #ffc46b);
  font-size: 0.6875rem;
  line-height: 1;
}

.campus-pet-picker__foot {
  display: flex;
  justify-content: flex-end;
  margin-top: 0.5rem;
}

.campus-pet-picker__cancel {
  min-height: 2.25rem;
  padding: 0 0.75rem;
  border: 0;
  border-radius: 9999px;
  background: transparent;
  color: var(--color-text-dim);
  font-size: 0.75rem;
  transition:
    background-color var(--motion-fast) var(--ease-standard),
    color var(--motion-fast) var(--ease-standard);
}

.campus-pet-picker__cancel:hover,
.campus-pet-picker__cancel:focus-visible {
  background: var(--fill-hover, rgba(244, 243, 237, 0.055));
  color: var(--color-text-muted);
}

@media (prefers-reduced-motion: reduce) {
  .campus-pet-picker__option,
  .campus-pet-picker__cancel {
    transition: none !important;
  }

  .campus-pet-picker__option:active {
    transform: none;
  }
}
</style>

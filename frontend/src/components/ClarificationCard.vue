<script setup>
import { computed, nextTick, ref, watch } from 'vue'

const INPUT_MAX_HEIGHT_PX = 164

const props = defineProps({
  isSending: {
    type: Boolean,
    default: false,
  },
  initialText: {
    type: String,
    default: '',
  },
})

const emit = defineEmits(['submit', 'cancel'])

const text = ref(props.initialText)
const textareaRef = ref(null)
const labelId = `clarification-answer-label-${Math.random().toString(36).slice(2)}`
const canSubmit = computed(() => text.value.trim().length > 0 && !props.isSending)

function resizeTextarea() {
  const el = textareaRef.value
  if (!el) {
    return
  }
  el.style.height = 'auto'
  el.style.height = `${Math.min(el.scrollHeight, INPUT_MAX_HEIGHT_PX)}px`
}

function submit() {
  if (!canSubmit.value) {
    return
  }
  emit('submit', text.value.trim())
}

function onEnter(event) {
  if (event.isComposing || event.shiftKey) {
    return
  }
  event.preventDefault()
  submit()
}

watch(text, () => {
  nextTick(resizeTextarea)
})

watch(
  () => props.initialText,
  (nextText) => {
    text.value = nextText
  },
)

nextTick(resizeTextarea)
</script>

<template>
  <form
    class="clarification-card relative w-full overflow-hidden rounded-ui-lg border border-edge-strong bg-ink-raised p-4 sm:p-5"
    aria-label="確認質問への回答"
    :aria-busy="isSending"
    @submit.prevent="submit"
  >
    <div class="clarification-card__rail" aria-hidden="true"></div>
    <div class="flex items-center gap-2.5">
      <span class="h-2 w-2 rounded-full bg-brand-signal" aria-hidden="true"></span>
      <label :id="labelId" class="text-sm font-semibold leading-6 text-ink-paper">
        こちらにお答えください
      </label>
    </div>

    <div class="clarification-card__input mt-3 rounded-ui border border-edge bg-ink-surface px-3 py-2.5 transition duration-base ease-standard focus-within:border-brand-soft">
      <textarea
        ref="textareaRef"
        v-model="text"
        rows="3"
        class="max-h-[164px] min-h-24 w-full resize-none bg-transparent text-base leading-7 text-ink-paper outline-none placeholder:text-[var(--color-text-dim)] disabled:cursor-not-allowed"
        placeholder="わかる範囲で入力してください"
        :aria-labelledby="labelId"
        :disabled="isSending"
        @keydown.enter="onEnter"
      ></textarea>
    </div>

    <div class="mt-3 flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
      <button
        type="button"
        class="min-h-11 rounded-ui-sm px-3 py-2 text-sm text-[var(--color-text-dim)] underline underline-offset-4 transition duration-fast ease-standard hover:bg-fill-hover hover:text-[var(--color-text)] active:scale-[0.97] disabled:cursor-not-allowed disabled:opacity-55 motion-reduce:transform-none motion-reduce:transition-none"
        :disabled="isSending"
        @click="emit('cancel')"
      >
        この質問には答えずに続ける
      </button>
      <button
        type="submit"
        class="inline-flex min-h-11 min-w-28 items-center justify-center gap-2 rounded-ui-sm px-4 py-2 text-sm font-semibold transition duration-base ease-expressive enabled:bg-ink-paper enabled:text-[var(--color-paper-ink)] enabled:hover:-translate-y-0.5 enabled:active:scale-[0.94] disabled:cursor-not-allowed disabled:bg-fill-hover disabled:text-[var(--color-text-dim)] motion-reduce:transform-none motion-reduce:transition-none"
        :disabled="!canSubmit"
        aria-label="確認質問への回答を送信"
      >
        <span>{{ isSending ? '送信中…' : '回答する' }}</span>
        <svg v-if="!isSending" aria-hidden="true" class="h-4 w-4" viewBox="0 0 24 24" fill="none">
          <path d="M12 19V5M5 12l7-7 7 7" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" />
        </svg>
      </button>
    </div>
  </form>
</template>

<style scoped>
.clarification-card {
  box-shadow:
    var(--shadow-hairline),
    var(--shadow-raised);
}

.clarification-card__rail {
  position: absolute;
  inset: 0 auto 0 0;
  width: 0.1875rem;
  background: var(--color-signal);
}

.clarification-card__input:has(textarea:focus-visible) {
  outline: var(--composer-focus-ring-width) solid var(--color-signal-soft);
  outline-offset: 3px;
}

.clarification-card-enter-active {
  transition:
    opacity var(--motion-base) ease-out,
    transform var(--motion-base) var(--ease-expressive);
}

.clarification-card-leave-active {
  transition:
    opacity var(--motion-fast) ease-out,
    transform var(--motion-fast) var(--ease-standard);
}

.clarification-card-enter-from {
  opacity: 0;
  transform: translate3d(0, 0.75rem, 0) scale(0.985);
}

.clarification-card-leave-to {
  opacity: 0;
  transform: translate3d(0, -0.25rem, 0);
}

@media (prefers-reduced-motion: reduce) {
  .clarification-card-enter-active,
  .clarification-card-leave-active {
    transition: none !important;
  }

  .clarification-card-enter-from,
  .clarification-card-leave-to {
    opacity: 1;
    transform: none;
  }
}
</style>

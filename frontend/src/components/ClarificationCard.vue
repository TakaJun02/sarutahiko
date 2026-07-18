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
const textareaId = `clarification-answer-input-${Math.random().toString(36).slice(2)}`
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
    class="clarification-card w-full sm:max-w-xl"
    aria-label="確認質問への回答"
    :aria-busy="isSending"
    @submit.prevent="submit"
  >
    <div class="mb-2 flex items-center gap-2 px-1">
      <span class="h-1.5 w-1.5 rounded-full bg-brand-signal" aria-hidden="true"></span>
      <label
        :id="labelId"
        :for="textareaId"
        class="text-sm font-medium leading-6 text-[var(--color-text-muted)]"
      >
        ひとことだけ教えてください
      </label>
    </div>

    <div class="clarification-card__composer composer-shell flex items-end gap-2 rounded-[1.6rem] p-2">
      <textarea
        :id="textareaId"
        ref="textareaRef"
        v-model="text"
        rows="1"
        class="max-h-[164px] min-h-11 flex-1 resize-none bg-transparent px-3 py-2.5 text-base leading-6 text-[var(--color-text)] outline-none placeholder:text-[var(--color-text-dim)] focus-visible:outline-none disabled:cursor-not-allowed"
        placeholder="例：機械工学科、はい"
        :aria-labelledby="labelId"
        :disabled="isSending"
        @keydown.enter="onEnter"
      ></textarea>
      <button
        type="submit"
        class="grid h-11 w-11 shrink-0 place-items-center rounded-full transition duration-base ease-expressive enabled:bg-ink-paper enabled:text-[var(--color-paper-ink)] enabled:hover:-translate-y-0.5 enabled:active:scale-[0.94] disabled:cursor-not-allowed disabled:bg-fill-hover disabled:text-[var(--color-text-dim)] motion-reduce:transform-none motion-reduce:transition-none"
        :disabled="!canSubmit"
        :aria-label="isSending ? '回答を送信中' : '確認質問への回答を送信'"
      >
        <svg aria-hidden="true" class="h-5 w-5" viewBox="0 0 24 24" fill="none">
          <path d="M12 19V5M5 12l7-7 7 7" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" />
        </svg>
      </button>
    </div>

    <button
      type="button"
      class="mt-1 inline-flex min-h-11 items-center rounded-full px-3 text-sm text-[var(--color-text-muted)] transition duration-fast ease-standard hover:bg-fill-hover hover:text-[var(--color-text)] active:scale-[0.97] disabled:cursor-not-allowed disabled:opacity-55 motion-reduce:transform-none motion-reduce:transition-none"
      :disabled="isSending"
      @click="emit('cancel')"
    >
      答えずに続ける
    </button>
  </form>
</template>

<style scoped>
.clarification-card-enter-active {
  transition:
    opacity var(--motion-base) var(--ease-expressive),
    transform var(--motion-base) var(--ease-expressive);
}

.clarification-card-leave-active {
  transition:
    opacity var(--motion-fast) var(--ease-standard),
    transform var(--motion-fast) var(--ease-standard);
}

.clarification-card-enter-from {
  opacity: 0;
  transform: translate3d(0, 0.5rem, 0);
}

.clarification-card-leave-to {
  opacity: 0;
  transform: translate3d(0, 0.25rem, 0);
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

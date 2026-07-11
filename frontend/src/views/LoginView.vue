<script setup>
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import { useAuthStore } from '../stores/auth'

const TYPE_DELAY_MS = 150
const DELETE_DELAY_MS = 75
const PHRASE_PAUSE_MS = 2000
const DELETE_PAUSE_MS = 500

const typewriterPhrases = [
  '本荘キャンパスの「知りたい」に、ぜんぶ答える',
  '聞いてみよう。キャンパスのこと、ぜんぶ',
  '学科のこと、施設のこと、入試のこと',
  'あなたの進路選びに、たしかな情報を',
  'オープンキャンパス2026へ、ようこそ',
  '分からないことは、その場で解決',
  '秋田県立大学のいまを、案内する',
  'ここからの一歩を、いっしょに',
]

const roles = [
  { value: 'highschool', label: '高校生' },
  { value: 'parent', label: '保護者' },
  { value: 'other', label: 'その他' },
]

const auth = useAuthStore()
const router = useRouter()
const route = useRoute()

const mode = ref('register')
const name = ref('')
const role = ref('highschool')
const error = ref('')
const isSubmitting = ref(false)
const displayedPhrase = ref('')
const prefersReducedMotion = ref(false)
const phraseIndex = ref(0)
const characterIndex = ref(0)
const isDeleting = ref(false)

let typewriterTimer = null
let reducedMotionQuery = null

const isRegister = computed(() => mode.value === 'register')
const ctaLabel = computed(() => (isRegister.value ? 'はじめる' : 'ログイン'))
const switchLabel = computed(() => (isRegister.value ? 'ログインはこちら' : '新規登録'))
const ctaClass = computed(() =>
  isRegister.value
    ? 'bg-white text-black hover:bg-zinc-100'
    : 'bg-zinc-800 text-white hover:bg-zinc-700',
)

function clearTypewriterTimer() {
  if (typewriterTimer) {
    window.clearTimeout(typewriterTimer)
    typewriterTimer = null
  }
}

function scheduleTypewriter(delay) {
  clearTypewriterTimer()
  typewriterTimer = window.setTimeout(runTypewriterStep, delay)
}

function resetTypewriter() {
  phraseIndex.value = 0
  characterIndex.value = 0
  isDeleting.value = false
  displayedPhrase.value = ''
}

function runTypewriterStep() {
  if (prefersReducedMotion.value) {
    displayedPhrase.value = typewriterPhrases[0]
    return
  }

  const phrase = typewriterPhrases[phraseIndex.value]
  if (!isDeleting.value) {
    const nextLength = characterIndex.value + 1
    characterIndex.value = nextLength
    displayedPhrase.value = phrase.slice(0, nextLength)

    if (nextLength >= phrase.length) {
      isDeleting.value = true
      scheduleTypewriter(PHRASE_PAUSE_MS)
      return
    }
    scheduleTypewriter(TYPE_DELAY_MS)
    return
  }

  const nextLength = Math.max(characterIndex.value - 1, 0)
  characterIndex.value = nextLength
  displayedPhrase.value = phrase.slice(0, nextLength)

  if (nextLength === 0) {
    isDeleting.value = false
    phraseIndex.value = (phraseIndex.value + 1) % typewriterPhrases.length
    scheduleTypewriter(DELETE_PAUSE_MS)
    return
  }
  scheduleTypewriter(DELETE_DELAY_MS)
}

function syncReducedMotion() {
  prefersReducedMotion.value = Boolean(reducedMotionQuery?.matches)
  clearTypewriterTimer()

  if (prefersReducedMotion.value) {
    displayedPhrase.value = typewriterPhrases[0]
    return
  }

  resetTypewriter()
  scheduleTypewriter(TYPE_DELAY_MS)
}

function validateName() {
  if (!name.value) {
    return 'ニックネームを入力してください。'
  }
  if (name.value.trim() !== name.value) {
    return '前後に空白を入れないでください。'
  }
  if (name.value.length > 20) {
    return 'ニックネームは20文字以内で入力してください。'
  }
  return ''
}

function toggleMode() {
  mode.value = isRegister.value ? 'login' : 'register'
  error.value = ''
}

async function submit() {
  const validationError = validateName()
  if (validationError || isSubmitting.value) {
    error.value = validationError
    return
  }

  isSubmitting.value = true
  error.value = ''
  try {
    if (isRegister.value) {
      await auth.register(name.value, role.value)
    } else {
      await auth.login(name.value)
    }
    router.replace(route.query.redirect || '/app/chat')
  } catch (submitError) {
    error.value = submitError.message || 'ログインに失敗しました。'
  } finally {
    isSubmitting.value = false
  }
}

function onEnter(event) {
  if (event.isComposing) {
    event.preventDefault()
    return
  }
  event.preventDefault()
  submit()
}

onMounted(() => {
  reducedMotionQuery = window.matchMedia('(prefers-reduced-motion: reduce)')
  syncReducedMotion()
  if (reducedMotionQuery.addEventListener) {
    reducedMotionQuery.addEventListener('change', syncReducedMotion)
  } else {
    reducedMotionQuery.addListener(syncReducedMotion)
  }
})

onBeforeUnmount(() => {
  clearTypewriterTimer()
  if (reducedMotionQuery?.removeEventListener) {
    reducedMotionQuery.removeEventListener('change', syncReducedMotion)
  } else {
    reducedMotionQuery?.removeListener?.(syncReducedMotion)
  }
})
</script>

<template>
  <main class="login-page flex min-h-svh flex-col overflow-hidden bg-white text-zinc-900">
    <section class="bg-noise flex flex-1 items-center justify-center px-6 py-10 text-center">
      <h1 class="max-w-4xl text-4xl font-bold leading-tight tracking-normal text-zinc-900 sm:text-5xl">
        <span>{{ displayedPhrase }}</span>
        <span
          class="login-type-cursor"
          :class="{ 'login-type-cursor--static': prefersReducedMotion }"
          aria-hidden="true"
        ></span>
      </h1>
    </section>

    <footer class="login-sheet rounded-t-3xl bg-black p-6 text-white sm:p-8">
      <form class="mx-auto w-full max-w-md space-y-5" @submit.prevent="submit">
        <p v-if="error" class="rounded-xl bg-red-900/50 px-4 py-3 text-sm text-red-100">
          {{ error }}
        </p>

        <label class="block">
          <span class="mb-2 block text-sm text-zinc-300">ニックネーム</span>
          <input
            v-model="name"
            class="w-full rounded-xl bg-zinc-800 px-4 py-3 text-base text-white outline-none transition placeholder:text-zinc-500 focus:ring-2 focus:ring-white"
            placeholder="例: さくら"
            autocomplete="nickname"
            maxlength="21"
            @keydown.enter="onEnter"
          />
        </label>

        <div v-if="isRegister" class="space-y-2">
          <p class="text-sm text-zinc-300">属性</p>
          <div class="grid grid-cols-3 gap-2">
            <button
              v-for="roleOption in roles"
              :key="roleOption.value"
              type="button"
              class="rounded-xl px-3 py-3 text-sm font-medium transition"
              :class="role === roleOption.value ? 'bg-white text-black' : 'bg-zinc-800 text-zinc-300 hover:bg-zinc-700 hover:text-white'"
              @click="role = roleOption.value"
            >
              {{ roleOption.label }}
            </button>
          </div>
        </div>

        <button
          type="submit"
          class="flex w-full items-center justify-center rounded-xl px-4 py-3 text-base font-semibold transition active:scale-[0.99] disabled:cursor-not-allowed disabled:opacity-60"
          :class="ctaClass"
          :disabled="isSubmitting"
        >
          <span v-if="isSubmitting" class="inline-flex items-center gap-2">
            <span class="h-5 w-5 animate-spin rounded-full border-2 border-current border-r-transparent"></span>
            処理中...
          </span>
          <span v-else>{{ ctaLabel }}</span>
        </button>

        <button
          type="button"
          class="w-full rounded-xl bg-zinc-800 px-4 py-3 text-base font-semibold text-white transition hover:bg-zinc-700"
          @click="toggleMode"
        >
          {{ switchLabel }}
        </button>
      </form>
    </footer>
  </main>
</template>

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

const auth = useAuthStore()
const router = useRouter()
const route = useRoute()

const mode = ref('register')
const name = ref('')
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
    ? 'bg-ink-paper text-[#11130f] hover:bg-white'
    : 'bg-brand-signal text-[#151713] hover:bg-brand-soft',
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
      await auth.register(name.value)
    } else {
      await auth.login(name.value)
    }
    router.replace(route.query.redirect || '/chat')
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
  <main class="login-page flex min-h-dvh flex-col overflow-x-hidden text-[#171916]">
    <section class="login-hero flex min-h-[31rem] flex-1">
      <div class="relative z-[1] mx-auto flex w-full max-w-[82rem] flex-col px-6 pb-8 pt-6 sm:px-10 sm:pb-10 sm:pt-8 lg:px-16 lg:pb-12">
        <header class="login-brand flex items-center justify-between gap-6 pl-4 sm:pl-5">
          <div class="flex min-w-0 items-center gap-3">
            <img
              src="/app-icon.png"
              alt=""
              class="h-10 w-10 shrink-0 rounded-ui-sm shadow-[0_8px_24px_-14px_rgba(23,25,22,0.55)]"
            />
            <div class="min-w-0">
              <p class="truncate text-[13px] font-semibold tracking-[-0.01em] sm:text-sm">本荘キャンパス案内 AI</p>
              <p class="font-display mt-0.5 truncate text-[10px] font-medium uppercase tracking-[0.16em] text-black/55">
                Akita Prefectural University
              </p>
            </div>
          </div>
          <div class="hidden shrink-0 items-center gap-3 sm:flex">
            <span class="h-1.5 w-1.5 rounded-full bg-brand-signal" aria-hidden="true"></span>
            <span class="font-display text-[10px] font-medium uppercase tracking-[0.18em] text-black/50">Open Campus / 2026</span>
          </div>
        </header>

        <div class="login-hero-copy flex flex-1 items-center py-8 pl-4 sm:pl-5 lg:py-10">
          <h1 class="min-h-[3.75em] max-w-[68rem] text-balance text-[clamp(2.1rem,5vw,4.6rem)] font-bold leading-[1.18] tracking-[-0.045em] text-[#171916] lg:min-h-[2.45em]">
            <span>{{ displayedPhrase }}</span>
            <span
              class="login-type-cursor"
              :class="{ 'login-type-cursor--static': prefersReducedMotion }"
              aria-hidden="true"
            ></span>
          </h1>
        </div>

        <div class="login-hero-meta flex items-end justify-between gap-8 pl-4 sm:pl-5">
          <p class="max-w-sm text-xs leading-5 text-black/50 sm:text-[13px]">
            学科、施設、アクセス。当日の「知りたい」を、ここで。
          </p>
          <div class="hidden items-end gap-4 lg:flex" aria-hidden="true">
            <span class="font-display text-[10px] font-medium uppercase tracking-[0.2em] text-black/55">Honjo Campus</span>
            <span class="font-display text-4xl font-medium leading-none tracking-[-0.06em] text-black/75">07.19</span>
          </div>
        </div>
      </div>
    </section>

    <footer class="login-sheet rounded-t-sheet bg-[#111310] px-6 pt-6 text-white sm:px-10 sm:pt-8 lg:flex lg:min-h-72 lg:items-center lg:px-16">
      <div class="mx-auto grid w-full max-w-[74rem] gap-6 lg:grid-cols-[0.72fr_1.28fr] lg:items-center lg:gap-16">
        <div class="hidden lg:block">
          <div class="flex items-center gap-3">
            <span class="font-display text-[10px] font-semibold uppercase tracking-[0.2em] text-brand-soft">Visitor desk</span>
            <span class="h-px w-10 bg-white/15" aria-hidden="true"></span>
            <span class="font-display text-[10px] tracking-[0.18em] text-white/40">01</span>
          </div>
          <h2 class="mt-3 text-2xl font-semibold tracking-[-0.035em]">まず、呼び名を教えてください。</h2>
          <p class="mt-2 max-w-md text-sm leading-6 text-white/55">パスワードは不要です。ニックネームだけで案内を始められます。</p>
        </div>

        <form class="w-full" @submit.prevent="submit">
          <div class="mb-4 flex items-end justify-between gap-4 lg:hidden">
            <div>
              <p class="font-display text-[10px] font-semibold uppercase tracking-[0.2em] text-brand-soft">Visitor desk / 01</p>
              <h2 class="mt-1.5 text-lg font-semibold tracking-[-0.025em]">案内を始める</h2>
            </div>
            <span class="font-display text-[10px] uppercase tracking-[0.16em] text-white/45">No password</span>
          </div>

        <p
          v-if="error"
            class="mb-4 flex items-start gap-2.5 rounded-ui-sm border border-red-400/25 bg-red-400/10 px-4 py-3 text-sm leading-6 text-red-100"
          role="alert"
        >
          <svg aria-hidden="true" class="mt-1 h-4 w-4 shrink-0" viewBox="0 0 24 24" fill="none">
            <path d="M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18z M12 8v5 M12 16.5h.01" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" />
          </svg>
          {{ error }}
        </p>

          <div class="grid gap-3 sm:grid-cols-[minmax(0,1fr)_10.5rem] sm:items-end">
            <label class="block">
              <span class="mb-2 block text-xs font-medium tracking-[0.04em] text-white/60">ニックネーム</span>
              <input
                v-model="name"
                class="min-h-14 w-full rounded-ui border border-white/10 bg-white/[0.065] px-4 py-3 text-base text-white outline-none transition duration-base ease-standard placeholder:text-white/45 hover:border-white/20 hover:bg-white/[0.08] focus:border-white/35 focus:bg-white/[0.08]"
                placeholder="例: さくら"
                autocomplete="nickname"
                maxlength="21"
                @keydown.enter="onEnter"
              />
            </label>

            <button
              type="submit"
              class="flex min-h-14 w-full items-center justify-center rounded-ui px-4 py-3 text-base font-semibold transition duration-base ease-expressive hover:-translate-y-0.5 active:translate-y-0 active:scale-[0.98] disabled:cursor-not-allowed disabled:opacity-55 disabled:hover:translate-y-0 disabled:active:scale-100"
              :class="ctaClass"
              :disabled="isSubmitting"
            >
              <span v-if="isSubmitting" class="inline-flex items-center gap-2">
                <span class="h-5 w-5 animate-spin rounded-full border-2 border-current border-r-transparent"></span>
                処理中...
              </span>
              <span v-else>{{ ctaLabel }}</span>
            </button>
          </div>

          <div class="mt-3 flex min-h-11 items-center justify-between gap-4 border-t border-white/[0.07] pt-3">
            <p class="text-xs text-white/40">{{ isRegister ? 'すでに登録済みですか？' : 'はじめて利用しますか？' }}</p>
            <button
              type="button"
              class="min-h-11 shrink-0 rounded-ui-sm px-3 text-sm font-semibold text-white/80 underline decoration-white/20 underline-offset-4 transition duration-fast ease-standard hover:bg-white/[0.06] hover:text-white hover:decoration-white/60 active:scale-[0.98]"
              @click="toggleMode"
            >
              {{ switchLabel }}
            </button>
          </div>
        </form>
      </div>
    </footer>
  </main>
</template>

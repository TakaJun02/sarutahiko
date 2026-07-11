<script setup>
import { computed, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import { useAuthStore } from '../stores/auth'

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
const isLeaving = ref(false)

const isRegister = computed(() => mode.value === 'register')
const ctaLabel = computed(() => (isRegister.value ? 'はじめる' : 'つづける'))
const switchLabel = computed(() => (isRegister.value ? '登録済みの方はこちら' : 'はじめての方はこちら'))

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
    isLeaving.value = true
    window.setTimeout(() => {
      router.replace(route.query.redirect || '/app/chat')
    }, 280)
  } catch (submitError) {
    error.value = submitError.message || 'ログインに失敗しました。'
  } finally {
    isSubmitting.value = false
  }
}

function onEnter(event) {
  if (event.isComposing) {
    return
  }
  submit()
}
</script>

<template>
  <main class="login-shell min-h-svh overflow-hidden bg-[#0f1115] px-4 py-8 text-white">
    <div class="aurora aurora-coral"></div>
    <div class="aurora aurora-sun"></div>
    <div class="aurora aurora-mint"></div>

    <section
      class="login-card relative z-10 mx-auto flex min-h-[calc(100svh-4rem)] w-full max-w-md items-center justify-center"
      :class="{ 'login-card-leave': isLeaving }"
    >
      <div class="w-full rounded-2xl border border-white/10 bg-white/[0.075] px-6 py-7 shadow-glass backdrop-blur-2xl sm:px-8 sm:py-9">
        <div class="mb-7 flex justify-center">
          <img
            src="/app-icon.png"
            alt="本荘キャンパス案内 AI"
            class="h-16 w-16 rounded-full shadow-[0_0_26px_rgba(255,255,255,0.18)]"
          />
        </div>

        <div class="mb-8 text-center">
          <p class="text-3xl font-semibold tracking-normal text-white">こんにちは。</p>
          <h1 class="mt-2 bg-gradient-to-r from-brand-coral via-brand-sun to-brand-mint bg-clip-text text-2xl font-semibold leading-tight tracking-normal text-transparent">
            秋田県立大学 本荘キャンパス案内 AI です
          </h1>
        </div>

        <form class="space-y-5" @submit.prevent="submit">
          <label class="block">
            <span class="mb-2 block text-sm text-white/68">ニックネーム</span>
            <input
              v-model="name"
              class="w-full rounded-2xl border border-white/10 bg-black/25 px-4 py-3 text-base text-white outline-none transition placeholder:text-white/30 focus:border-transparent focus:ring-2 focus:ring-brand-mint/70"
              placeholder="例: さくら"
              autocomplete="nickname"
              maxlength="21"
              @keydown.enter.prevent="onEnter"
            />
          </label>

          <div v-if="isRegister" class="space-y-2">
            <p class="text-sm text-white/68">属性</p>
            <div class="grid grid-cols-3 gap-2 rounded-2xl border border-white/10 bg-black/20 p-1.5">
              <button
                v-for="roleOption in roles"
                :key="roleOption.value"
                type="button"
                class="rounded-xl px-2 py-2.5 text-sm transition"
                :class="role === roleOption.value ? 'bg-white text-[#101217] shadow-sm' : 'text-white/68 hover:bg-white/8 hover:text-white'"
                @click="role = roleOption.value"
              >
                {{ roleOption.label }}
              </button>
            </div>
          </div>

          <p v-if="error" class="text-sm text-red-300">{{ error }}</p>

          <button
            type="submit"
            class="w-full rounded-2xl bg-white px-4 py-3 text-base font-semibold text-[#101217] transition hover:shadow-[0_0_26px_rgba(105,240,174,0.28)] active:scale-[0.99] disabled:cursor-not-allowed disabled:opacity-60"
            :disabled="isSubmitting"
          >
            {{ isSubmitting ? '送信中…' : ctaLabel }}
          </button>
        </form>

        <button
          type="button"
          class="mt-6 w-full text-center text-sm text-white/60 transition hover:text-white"
          @click="toggleMode"
        >
          {{ switchLabel }}
        </button>
      </div>
    </section>
  </main>
</template>

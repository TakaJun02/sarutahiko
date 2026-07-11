<script setup>
import { nextTick, onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'

import LoadingSpinner from '../components/LoadingSpinner.vue'
import MarkdownRenderer from '../components/MarkdownRenderer.vue'
import { useAuthStore } from '../stores/auth'
import { useChatStore } from '../stores/chat'

const auth = useAuthStore()
const chat = useChatStore()
const router = useRouter()

const draft = ref('')
const messagesEnd = ref(null)
const inputRef = ref(null)

async function send() {
  const text = draft.value
  if (!text.trim() || chat.isSending) {
    return
  }
  draft.value = ''
  try {
    await chat.sendMessage(text)
  } catch (error) {
    if (error.status === 401) {
      auth.clearSession()
      router.replace('/login')
    }
  } finally {
    await nextTick()
    inputRef.value?.focus()
  }
}

function onEnter(event) {
  if (event.isComposing || event.shiftKey) {
    return
  }
  event.preventDefault()
  send()
}

function logout() {
  auth.clearSession()
  chat.reset()
  router.replace('/login')
}

async function scrollToBottom() {
  await nextTick()
  messagesEnd.value?.scrollIntoView({ behavior: 'smooth', block: 'end' })
}

watch(
  () => chat.messages.map((message) => `${message.id}:${message.content.length}:${message.statusText}`).join('|'),
  scrollToBottom,
)

onMounted(() => {
  inputRef.value?.focus()
})
</script>

<template>
  <main class="flex min-h-svh flex-col bg-[#0f1115] text-white">
    <header class="sticky top-0 z-20 border-b border-white/8 bg-[#0f1115]/88 px-4 py-3 backdrop-blur-xl">
      <div class="mx-auto flex max-w-3xl items-center justify-between gap-3">
        <div class="flex min-w-0 items-center gap-3">
          <img src="/app-icon.png" alt="本荘キャンパス案内 AI" class="h-9 w-9 rounded-full" />
          <div class="min-w-0">
            <h1 class="truncate text-base font-semibold tracking-normal">本荘キャンパス案内 AI</h1>
            <p class="truncate text-xs text-white/50">{{ auth.user?.name }}{{ auth.roleLabel ? ` / ${auth.roleLabel}` : '' }}</p>
          </div>
        </div>
        <button
          type="button"
          class="rounded-full border border-white/10 px-3 py-1.5 text-sm text-white/68 transition hover:border-white/24 hover:text-white"
          @click="logout"
        >
          ログアウト
        </button>
      </div>
    </header>

    <section class="mx-auto flex w-full max-w-3xl flex-1 flex-col px-4 pb-4 pt-5">
      <div class="flex-1 space-y-5 pb-4">
        <div v-if="chat.messages.length === 0" class="mx-auto flex max-w-xl flex-col items-center justify-center py-14 text-center">
          <img src="/app-icon.png" alt="" class="mb-5 h-14 w-14 rounded-full opacity-90" />
          <h2 class="text-2xl font-semibold tracking-normal">知りたいことを聞いてください。</h2>
        </div>

        <article
          v-for="message in chat.messages"
          :key="message.id"
          class="flex"
          :class="message.role === 'user' ? 'justify-end' : 'justify-start'"
        >
          <div
            class="max-w-[88%] sm:max-w-[78%]"
            :class="message.role === 'user' ? 'rounded-2xl bg-white px-4 py-3 text-[#111318]' : 'text-white'"
          >
            <template v-if="message.role === 'assistant'">
              <LoadingSpinner v-if="message.pending" :text="message.statusText || 'お待ちください…'" />
              <div v-else class="space-y-3">
                <MarkdownRenderer :content="message.content" />
                <div v-if="message.sources.length" class="border-t border-white/10 pt-3">
                  <p class="mb-2 text-xs text-white/44">出典</p>
                  <ul class="space-y-1">
                    <li v-for="source in message.sources" :key="source.url">
                      <a
                        class="text-sm text-brand-mint underline-offset-4 hover:underline"
                        :href="source.url"
                        target="_blank"
                        rel="noreferrer"
                      >
                        {{ source.title }}
                      </a>
                    </li>
                  </ul>
                </div>
              </div>
            </template>
            <p v-else class="whitespace-pre-wrap break-words text-base leading-7">{{ message.content }}</p>
          </div>
        </article>
        <div ref="messagesEnd"></div>
      </div>

      <form class="sticky bottom-0 border-t border-white/8 bg-[#0f1115]/92 py-3 backdrop-blur-xl" @submit.prevent="send">
        <div class="flex items-end gap-2 rounded-3xl border border-white/10 bg-white/[0.06] p-2 shadow-[0_-20px_60px_rgba(0,0,0,0.16)]">
          <textarea
            ref="inputRef"
            v-model="draft"
            rows="1"
            class="max-h-32 min-h-11 flex-1 resize-none bg-transparent px-3 py-2.5 text-base leading-6 text-white outline-none placeholder:text-white/35"
            placeholder="質問を入力"
            @keydown.enter="onEnter"
          ></textarea>
          <button
            type="submit"
            class="grid h-11 w-11 shrink-0 place-items-center rounded-full bg-white text-[#101217] transition hover:shadow-[0_0_18px_rgba(105,240,174,0.28)] disabled:cursor-not-allowed disabled:opacity-45"
            :disabled="!draft.trim() || chat.isSending"
            aria-label="送信"
          >
            <svg aria-hidden="true" class="h-5 w-5" viewBox="0 0 24 24" fill="none">
              <path d="M5 12h14M13 6l6 6-6 6" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" />
            </svg>
          </button>
        </div>
        <p v-if="chat.error" class="mt-2 text-sm text-red-300">{{ chat.error }}</p>
      </form>
    </section>
  </main>
</template>

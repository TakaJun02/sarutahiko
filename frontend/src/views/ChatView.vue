<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import LoadingSpinnerV5 from '../components/LoadingSpinnerV5.vue'
import MarkdownRenderer from '../components/MarkdownRenderer.vue'
import ThreadSidebar from '../components/ThreadSidebar.vue'
import { useAuthStore } from '../stores/auth'
import { useChatStore } from '../stores/chat'

const OPEN_CAMPUS_DATE = '2026-07-19'
const INPUT_MAX_HEIGHT_PX = 160

// Suggested first questions for the empty state (tap inserts into the input).
const suggestions = [
  {
    label: 'アクセス方法は？',
    icon: 'M12 21s-6.5-5.4-6.5-10a6.5 6.5 0 1 1 13 0c0 4.6-6.5 10-6.5 10z M12 13a2 2 0 1 0 0-4 2 2 0 0 0 0 4z',
  },
  {
    label: '模擬講義は何がある？',
    icon: 'M2.5 9.5 12 5l9.5 4.5L12 14 2.5 9.5z M6.5 11.6v3.9c0 1.3 2.5 2.4 5.5 2.4s5.5-1.1 5.5-2.4v-3.9 M21 10v4.5',
  },
  {
    label: '学食メニューは？',
    icon: 'M6 3v5.5a2 2 0 0 0 4 0V3 M8 3v18 M16.5 3a2.6 4.2 0 1 0 0 8.4 2.6 4.2 0 0 0 0-8.4z M16.5 11.4V21',
  },
  {
    label: '無料送迎バスの時刻は？',
    icon: 'M5 4h14a1.5 1.5 0 0 1 1.5 1.5V16a2 2 0 0 1-2 2H5.5a2 2 0 0 1-2-2V5.5A1.5 1.5 0 0 1 5 4z M3.5 11h17 M8 21v-3 M16 21v-3 M7.5 15h.01 M16.5 15h.01',
  },
]

const auth = useAuthStore()
const chat = useChatStore()
const router = useRouter()
const route = useRoute()

const draft = ref('')
const drawerOpen = ref(false)
const messagesEnd = ref(null)
const inputRef = ref(null)
const footerRef = ref(null)
const footerClearancePx = ref(224)

let footerResizeObserver = null
let pendingScrollBehavior = null

// Days until Open Campus 2026, computed against the JST calendar day.
const countdownLabel = computed(() => {
  const todayJst = new Intl.DateTimeFormat('en-CA', { timeZone: 'Asia/Tokyo' }).format(new Date())
  const diffDays = Math.round((Date.parse(OPEN_CAMPUS_DATE) - Date.parse(todayJst)) / 86_400_000)
  if (diffDays > 0) {
    return `オープンキャンパス2026まで あと${diffDays}日`
  }
  if (diffDays === 0) {
    return 'オープンキャンパス2026 本日開催！'
  }
  return ''
})

async function send() {
  const text = draft.value
  if (!text.trim() || chat.isSending) {
    return
  }
  draft.value = ''
  try {
    await chat.sendMessage(text)
  } catch (error) {
    handleAuthError(error)
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

function applySuggestion(text) {
  draft.value = text
  nextTick(() => {
    inputRef.value?.focus()
  })
}

function autoResizeInput() {
  const el = inputRef.value
  if (!el) {
    return
  }
  el.style.height = 'auto'
  el.style.height = `${Math.min(el.scrollHeight, INPUT_MAX_HEIGHT_PX)}px`
}

function sourceTypeLabel(type) {
  return type === 'knowledge' ? '学内ナレッジ' : 'Web'
}

function logout() {
  auth.clearSession()
  chat.reset()
  router.replace('/login')
}

function handleAuthError(error) {
  if (error?.status === 401) {
    logout()
    return true
  }
  return false
}

function closeDrawer() {
  drawerOpen.value = false
}

function selectThread(threadId) {
  closeDrawer()
  if (threadId === chat.threadId) {
    return
  }
  router.push(`/chat/${threadId}`)
}

function startNewChat() {
  closeDrawer()
  if (route.params.threadId) {
    router.push('/chat')
  } else {
    chat.newChat()
  }
}

async function renameThread(threadId) {
  const thread = chat.threads.find((item) => item.id === threadId)
  const input = window.prompt('スレッド名（1〜60文字）', thread?.title || '')
  if (input === null) {
    return
  }
  const title = input.trim()
  if (!title || title.length > 60) {
    window.alert('スレッド名は1〜60文字で入力してください。')
    return
  }
  try {
    await chat.renameThread(threadId, title)
  } catch (error) {
    if (handleAuthError(error)) {
      return
    }
    window.alert(error.message || 'スレッド名を変更できませんでした。')
  }
}

async function removeThread(threadId) {
  if (!window.confirm('この会話を削除しますか？この操作は取り消せません。')) {
    return
  }
  const wasCurrent = threadId === chat.threadId || threadId === route.params.threadId
  try {
    await chat.deleteThread(threadId)
  } catch (error) {
    if (handleAuthError(error)) {
      return
    }
    window.alert(error.message || '会話を削除できませんでした。')
    return
  }
  closeDrawer()
  if (wasCurrent) {
    router.replace('/chat')
  }
}

async function syncThreadFromRoute(threadId) {
  if (!threadId) {
    if (chat.threadId) {
      chat.newChat()
    }
    return
  }
  if (threadId === chat.threadId) {
    return
  }
  // Restoring a persisted thread should land at the bottom instantly.
  pendingScrollBehavior = 'auto'
  try {
    await chat.openThread(threadId)
  } catch (error) {
    pendingScrollBehavior = null
    if (handleAuthError(error)) {
      return
    }
    router.replace('/chat')
  }
}

async function scrollToBottom() {
  await nextTick()
  updateFooterClearance()
  const behavior = pendingScrollBehavior || 'smooth'
  pendingScrollBehavior = null
  messagesEnd.value?.scrollIntoView({ behavior, block: 'end' })
}

function updateFooterClearance() {
  const footerHeight = footerRef.value?.offsetHeight || 0
  if (footerHeight > 0) {
    footerClearancePx.value = Math.ceil(footerHeight + 24)
  }
}

watch(draft, () => {
  nextTick(autoResizeInput)
})

watch(
  () => chat.messages.map((message) => {
    const sourceKey = message.sources.map((source) => source.url).join(',')
    return `${message.clientId || message.id}:${message.content.length}:${message.statusText}:${message.statusStep}:${sourceKey}`
  }).join('|'),
  scrollToBottom,
)

watch(
  () => route.params.threadId,
  (threadId) => {
    syncThreadFromRoute(threadId || null)
  },
)

watch(
  () => chat.threadId,
  (threadId) => {
    if (threadId && route.params.threadId !== threadId) {
      router.replace(`/chat/${threadId}`)
    }
  },
)

onMounted(() => {
  inputRef.value?.focus()
  autoResizeInput()
  updateFooterClearance()
  if (typeof ResizeObserver !== 'undefined' && footerRef.value) {
    footerResizeObserver = new ResizeObserver(updateFooterClearance)
    footerResizeObserver.observe(footerRef.value)
  }
  chat.loadThreads().catch((error) => {
    handleAuthError(error)
  })
  syncThreadFromRoute(route.params.threadId || null)
})

onBeforeUnmount(() => {
  footerResizeObserver?.disconnect()
})
</script>

<template>
  <div class="flex h-dvh overflow-hidden bg-ink-base text-white">
    <aside class="hidden w-72 shrink-0 border-r border-edge lg:block">
      <ThreadSidebar
        :threads="chat.threads"
        :current-thread-id="chat.threadId"
        :disabled="chat.isSending"
        :user-name="auth.user?.name || ''"
        @select="selectThread"
        @new-chat="startNewChat"
        @rename="renameThread"
        @delete="removeThread"
        @logout="logout"
      />
    </aside>

    <div
      class="fixed inset-0 z-40 lg:hidden"
      :class="drawerOpen ? '' : 'pointer-events-none'"
      :aria-hidden="!drawerOpen"
    >
      <div
        class="absolute inset-0 bg-black/60 transition-opacity duration-200 ease-out"
        :class="drawerOpen ? 'opacity-100' : 'opacity-0'"
        @click="closeDrawer"
      ></div>
      <aside
        class="absolute inset-y-0 left-0 w-72 max-w-[85vw] transform border-r border-edge shadow-glass transition-transform duration-200 ease-out"
        :class="drawerOpen ? 'translate-x-0' : '-translate-x-full'"
      >
        <ThreadSidebar
          :threads="chat.threads"
          :current-thread-id="chat.threadId"
          :disabled="chat.isSending"
          :user-name="auth.user?.name || ''"
          @select="selectThread"
          @new-chat="startNewChat"
          @rename="renameThread"
          @delete="removeThread"
          @logout="logout"
        />
      </aside>
    </div>

    <main class="flex h-full min-w-0 flex-1 flex-col overflow-y-auto">
      <header class="sticky top-0 z-20 bg-ink-base/85 backdrop-blur-xl">
        <div class="mx-auto flex max-w-3xl items-center gap-3 px-4 py-3">
          <button
            type="button"
            class="grid h-11 w-11 shrink-0 place-items-center rounded-xl text-white/65 transition duration-200 ease-out hover:bg-fill-hover hover:text-white active:scale-[0.97] lg:hidden"
            aria-label="会話履歴を開く"
            @click="drawerOpen = true"
          >
            <svg aria-hidden="true" class="h-5 w-5" viewBox="0 0 24 24" fill="none">
              <path d="M4 6h16M4 12h16M4 18h16" stroke="currentColor" stroke-width="2" stroke-linecap="round" />
            </svg>
          </button>
          <div class="flex min-w-0 items-center gap-3">
            <img src="/app-icon.png" alt="本荘キャンパス案内 AI" class="h-9 w-9 rounded-full shadow-soft" />
            <div class="min-w-0">
              <h1 class="truncate text-[15px] font-semibold tracking-tight">本荘キャンパス案内 AI</h1>
              <p class="truncate text-xs text-white/45">秋田県立大学 オープンキャンパス2026</p>
            </div>
          </div>
        </div>
        <div class="h-px w-full bg-brand-line opacity-30" aria-hidden="true"></div>
      </header>

      <section class="flex w-full flex-1 flex-col pt-6">
        <div class="flex flex-1 flex-col space-y-6" :style="{ paddingBottom: `${footerClearancePx}px` }">
          <div
            v-if="chat.messages.length === 0"
            class="mx-auto flex w-full max-w-2xl flex-1 flex-col items-center justify-center px-5 py-10 text-center"
          >
            <div class="relative mb-6">
              <div class="absolute -inset-5 rounded-full bg-brand-line opacity-25 blur-2xl" aria-hidden="true"></div>
              <img src="/app-icon.png" alt="" class="relative h-16 w-16 rounded-full shadow-soft" />
            </div>
            <h2 class="text-2xl font-bold leading-snug tracking-tight sm:text-[1.75rem]">
              こんにちは<template v-if="auth.user?.name">、{{ auth.user.name }} さん</template>。
            </h2>
            <p class="mt-2 text-[15px] leading-7 text-white/55">
              本荘キャンパスのこと、なんでも聞いてください。
            </p>
            <p
              v-if="countdownLabel"
              class="countdown-chip mt-6 inline-flex min-h-9 items-center gap-2 rounded-full px-4 py-1.5 text-sm font-medium text-white/90"
            >
              <span aria-hidden="true">🎪</span>{{ countdownLabel }}
            </p>
            <div class="mt-8 grid w-full gap-2.5 sm:grid-cols-2">
              <button
                v-for="suggestion in suggestions"
                :key="suggestion.label"
                type="button"
                class="group flex min-h-[52px] items-center gap-3 rounded-2xl border border-edge bg-ink-surface px-4 py-3 text-left text-sm text-white/75 transition duration-200 ease-out hover:border-edge-strong hover:bg-ink-raised hover:text-white active:scale-[0.97]"
                @click="applySuggestion(suggestion.label)"
              >
                <svg
                  aria-hidden="true"
                  class="h-5 w-5 shrink-0 text-white/35 transition duration-200 ease-out group-hover:text-brand-mint"
                  viewBox="0 0 24 24"
                  fill="none"
                >
                  <path :d="suggestion.icon" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" />
                </svg>
                <span class="flex-1">{{ suggestion.label }}</span>
                <svg
                  aria-hidden="true"
                  class="h-4 w-4 shrink-0 text-white/25 transition duration-200 ease-out group-hover:translate-x-0.5 group-hover:text-brand-mint"
                  viewBox="0 0 24 24"
                  fill="none"
                >
                  <path d="M5 12h14M13 6l6 6-6 6" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" />
                </svg>
              </button>
            </div>
          </div>

          <article
            v-for="message in chat.messages"
            :key="message.clientId || message.id"
            class="w-full px-4"
          >
            <div class="mx-auto w-full max-w-3xl">
              <template v-if="message.role === 'assistant'">
                <div class="w-full text-white">
                  <LoadingSpinnerV5
                    :mode="message.pending ? 'pending' : 'settled'"
                    :text="message.statusText || 'お待ちください…'"
                    :status-step="message.statusStep || 'generate'"
                  >
                    <div class="space-y-4">
                      <MarkdownRenderer v-if="message.content" :content="message.content" />
                      <div v-if="message.sources.length" class="border-t border-edge pt-3">
                        <p class="mb-2 text-xs font-medium tracking-wide text-white/45">出典</p>
                        <ul class="flex flex-wrap gap-2">
                          <li v-for="source in message.sources" :key="source.url">
                            <a
                              class="group flex min-h-9 items-center gap-2 rounded-full border border-edge bg-ink-surface py-1.5 pl-2 pr-3 text-xs text-white/70 transition duration-200 ease-out hover:border-edge-strong hover:bg-ink-raised hover:text-white"
                              :href="source.url"
                              target="_blank"
                              rel="noreferrer"
                            >
                              <span
                                class="inline-flex shrink-0 items-center gap-1 rounded-full px-2 py-0.5 text-[10px] font-semibold"
                                :class="source.type === 'knowledge'
                                  ? 'bg-brand-mint/15 text-brand-mint'
                                  : 'bg-brand-coral/15 text-brand-coral'"
                              >
                                <svg aria-hidden="true" class="h-3 w-3" viewBox="0 0 24 24" fill="none">
                                  <path
                                    v-if="source.type === 'knowledge'"
                                    d="M4 5.5A2.5 2.5 0 0 1 6.5 3H20v15.5H6.5A2.5 2.5 0 0 0 4 21V5.5z M4 18.5A2.5 2.5 0 0 1 6.5 16H20"
                                    stroke="currentColor"
                                    stroke-width="1.8"
                                    stroke-linecap="round"
                                    stroke-linejoin="round"
                                  />
                                  <path
                                    v-else
                                    d="M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18z M3 12h18 M12 3c2.4 2.4 3.6 5.6 3.6 9S14.4 18.6 12 21c-2.4-2.4-3.6-5.6-3.6-9S9.6 5.4 12 3z"
                                    stroke="currentColor"
                                    stroke-width="1.6"
                                    stroke-linecap="round"
                                    stroke-linejoin="round"
                                  />
                                </svg>
                                {{ sourceTypeLabel(source.type) }}
                              </span>
                              <span class="max-w-[14rem] truncate sm:max-w-[20rem]">{{ source.title }}</span>
                              <svg
                                aria-hidden="true"
                                class="h-3 w-3 shrink-0 text-white/30 transition duration-200 ease-out group-hover:text-white/70"
                                viewBox="0 0 24 24"
                                fill="none"
                              >
                                <path d="M14 5h5v5 M19 5l-9 9 M11 5H6a1 1 0 0 0-1 1v12a1 1 0 0 0 1 1h12a1 1 0 0 0 1-1v-5" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" />
                              </svg>
                            </a>
                          </li>
                        </ul>
                      </div>
                    </div>
                  </LoadingSpinnerV5>
                </div>
              </template>
              <div v-else class="flex justify-end">
                <p class="max-w-[88%] whitespace-pre-wrap break-words rounded-2xl rounded-br-md bg-gradient-to-b from-[#f6f7f9] to-[#e7eaef] px-4 py-2.5 text-base leading-7 text-[#14171d] shadow-soft sm:max-w-[78%]">
                  {{ message.content }}
                </p>
              </div>
            </div>
          </article>
          <div ref="messagesEnd" :style="{ scrollMarginBottom: `${footerClearancePx}px` }"></div>
        </div>

        <form
          ref="footerRef"
          class="sticky bottom-0 z-10 border-t border-edge bg-ink-base/90 px-4 pb-[calc(0.75rem_+_env(safe-area-inset-bottom))] pt-3 backdrop-blur-xl"
          @submit.prevent="send"
        >
          <div class="mx-auto w-full max-w-3xl">
            <div class="flex items-end gap-2 rounded-[1.75rem] border border-edge bg-ink-raised p-2 shadow-soft transition duration-200 ease-out focus-within:border-brand-mint/40 focus-within:shadow-glow-mint">
              <textarea
                ref="inputRef"
                v-model="draft"
                rows="1"
                class="max-h-40 min-h-11 flex-1 resize-none bg-transparent px-3 py-2.5 text-base leading-6 text-white outline-none placeholder:text-white/35"
                placeholder="質問を入力"
                @keydown.enter="onEnter"
              ></textarea>
              <button
                type="submit"
                class="grid h-11 w-11 shrink-0 place-items-center rounded-full text-[#101217] transition duration-200 ease-out enabled:bg-brand-line enabled:hover:shadow-[0_0_20px_rgba(105,240,174,0.35)] enabled:hover:brightness-110 enabled:active:scale-[0.95] disabled:cursor-not-allowed disabled:bg-white/10 disabled:text-white/30"
                :disabled="!draft.trim() || chat.isSending"
                aria-label="送信"
              >
                <svg aria-hidden="true" class="h-5 w-5" viewBox="0 0 24 24" fill="none">
                  <path d="M12 19V5M5 12l7-7 7 7" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" />
                </svg>
              </button>
            </div>
            <p
              v-if="chat.error"
              class="mt-2 flex items-center gap-2 rounded-xl border border-red-400/30 bg-red-500/10 px-3 py-2 text-sm text-red-200"
              role="alert"
            >
              <svg aria-hidden="true" class="h-4 w-4 shrink-0" viewBox="0 0 24 24" fill="none">
                <path d="M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18z M12 8v5 M12 16.5h.01" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" />
              </svg>
              {{ chat.error }}
            </p>
            <p class="mt-2 hidden text-center text-xs text-white/30 sm:block">
              Enter で送信 ・ Shift + Enter で改行
            </p>
          </div>
        </form>
      </section>
    </main>
  </div>
</template>

<script setup>
import { nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import LoadingSpinnerV5 from '../components/LoadingSpinnerV5.vue'
import MarkdownRenderer from '../components/MarkdownRenderer.vue'
import ThreadSidebar from '../components/ThreadSidebar.vue'
import { useAuthStore } from '../stores/auth'
import { useChatStore } from '../stores/chat'

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
  <div class="flex h-svh overflow-hidden bg-[#0f1115] text-white">
    <aside class="hidden w-72 shrink-0 border-r border-white/8 lg:block">
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
        class="absolute inset-0 bg-black/60 transition-opacity duration-200"
        :class="drawerOpen ? 'opacity-100' : 'opacity-0'"
        @click="closeDrawer"
      ></div>
      <aside
        class="absolute inset-y-0 left-0 w-72 max-w-[85vw] transform border-r border-white/8 shadow-glass transition-transform duration-200 ease-out"
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
      <header class="sticky top-0 z-20 border-b border-white/8 bg-[#0f1115]/88 px-4 py-3 backdrop-blur-xl">
        <div class="mx-auto flex max-w-3xl items-center gap-3">
          <button
            type="button"
            class="grid h-9 w-9 shrink-0 place-items-center rounded-lg text-white/68 transition hover:bg-white/[0.08] hover:text-white lg:hidden"
            aria-label="会話履歴を開く"
            @click="drawerOpen = true"
          >
            <svg aria-hidden="true" class="h-5 w-5" viewBox="0 0 24 24" fill="none">
              <path d="M4 6h16M4 12h16M4 18h16" stroke="currentColor" stroke-width="2" stroke-linecap="round" />
            </svg>
          </button>
          <div class="flex min-w-0 items-center gap-3">
            <img src="/app-icon.png" alt="本荘キャンパス案内 AI" class="h-9 w-9 rounded-full" />
            <div class="min-w-0">
              <h1 class="truncate text-base font-semibold tracking-normal">本荘キャンパス案内 AI</h1>
              <p class="truncate text-xs text-white/50">{{ auth.user?.name }}</p>
            </div>
          </div>
        </div>
      </header>

      <section class="flex w-full flex-1 flex-col pb-4 pt-5">
        <div class="flex-1 space-y-5" :style="{ paddingBottom: `${footerClearancePx}px` }">
          <div v-if="chat.messages.length === 0" class="mx-auto flex max-w-xl flex-col items-center justify-center px-4 py-14 text-center">
            <img src="/app-icon.png" alt="" class="mb-5 h-14 w-14 rounded-full opacity-90" />
            <h2 class="text-2xl font-semibold tracking-normal">知りたいことを聞いてください。</h2>
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
                    <div class="space-y-3">
                      <MarkdownRenderer v-if="message.content" :content="message.content" />
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
                  </LoadingSpinnerV5>
                </div>
              </template>
              <div v-else class="flex justify-end">
                <p class="max-w-[88%] whitespace-pre-wrap break-words rounded-2xl bg-white px-4 py-3 text-base leading-7 text-[#111318] sm:max-w-[78%]">
                  {{ message.content }}
                </p>
              </div>
            </div>
          </article>
          <div ref="messagesEnd" :style="{ scrollMarginBottom: `${footerClearancePx}px` }"></div>
        </div>

        <form ref="footerRef" class="sticky bottom-0 border-t border-white/8 bg-[#0f1115]/92 px-4 py-3 backdrop-blur-xl" @submit.prevent="send">
          <div class="mx-auto w-full max-w-3xl">
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
          </div>
        </form>
      </section>
    </main>
  </div>
</template>

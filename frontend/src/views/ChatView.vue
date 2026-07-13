<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import LoadingSpinnerV5 from '../components/LoadingSpinnerV5.vue'
import MarkdownRenderer from '../components/MarkdownRenderer.vue'
import ThreadSidebar from '../components/ThreadSidebar.vue'
import { useAuthStore } from '../stores/auth'
import { toFriendlyErrorMessage, useChatStore } from '../stores/chat'

const OPEN_CAMPUS_DATE = '2026-07-19'
// Line-grid aligned: 20px vertical padding + 24px line-height x 6 lines.
const INPUT_MAX_HEIGHT_PX = 164

// Suggested first questions for the empty state (tap inserts into the input).
const suggestions = [
  'アクセス方法は？',
  '模擬講義は何がある？',
  '学食メニューは？',
  '無料送迎バスの時刻は？',
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
const expandedSourceKeys = ref(new Set())

// Thread rename / delete confirmation dialog (replaces window.prompt/confirm).
const dialog = ref(null) // { kind: 'rename' | 'delete', threadId, threadTitle }
const dialogInput = ref('')
const dialogError = ref('')
const dialogBusy = ref(false)
const dialogInputRef = ref(null)
const dialogCancelRef = ref(null)

// Transient hint shown when Enter is pressed while a reply is streaming.
const busyHint = ref('')

let dialogReturnFocus = null
let busyHintTimer = null

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

function showBusyHint() {
  busyHint.value = '回答をまとめている途中です。少しだけ待っていてくださいね。'
  if (busyHintTimer) {
    window.clearTimeout(busyHintTimer)
  }
  busyHintTimer = window.setTimeout(() => {
    busyHint.value = ''
    busyHintTimer = null
  }, 2500)
}

async function send() {
  const text = draft.value
  if (!text.trim()) {
    return
  }
  if (chat.isSending) {
    showBusyHint()
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
  if (chat.isSending) {
    showBusyHint()
    return
  }
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

function messageSourceKey(message) {
  return message.clientId || message.id
}

function sourceRegionId(message) {
  const key = String(messageSourceKey(message)).replace(/[^A-Za-z0-9_-]/g, '-')
  return `message-sources-${key}`
}

function isSourcesExpanded(message) {
  return expandedSourceKeys.value.has(messageSourceKey(message))
}

function sourcesToggleLabel(message) {
  const action = isSourcesExpanded(message) ? '出典を折りたたむ' : '出典を展開する'
  return `${action}（${message.sources.length}件）`
}

function sourcesRegionLabel(message) {
  return `出典 ${message.sources.length}件`
}

function toggleSources(message) {
  const key = messageSourceKey(message)
  const nextKeys = new Set(expandedSourceKeys.value)
  if (nextKeys.has(key)) {
    nextKeys.delete(key)
  } else {
    nextKeys.add(key)
  }
  expandedSourceKeys.value = nextKeys
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

function openDialog(kind, threadId) {
  // The immediate trigger is a menu item that unmounts with its menu, so
  // prefer the thread row's persistent kebab button for focus restoration.
  const active = document.activeElement instanceof HTMLElement ? document.activeElement : null
  dialogReturnFocus = active?.closest('li')?.querySelector('[aria-haspopup="menu"]') || active
  const thread = chat.threads.find((item) => item.id === threadId)
  dialog.value = { kind, threadId, threadTitle: thread?.title || '' }
  dialogInput.value = kind === 'rename' ? thread?.title || '' : ''
  dialogError.value = ''
  nextTick(() => {
    if (kind === 'rename') {
      dialogInputRef.value?.focus()
      dialogInputRef.value?.select()
    } else {
      // Destructive confirm: land on the safe choice so a stray Enter
      // never deletes a conversation.
      dialogCancelRef.value?.focus()
    }
  })
}

function restoreDialogFocus() {
  const target = dialogReturnFocus && dialogReturnFocus.isConnected ? dialogReturnFocus : inputRef.value
  dialogReturnFocus = null
  nextTick(() => target?.focus())
}

function renameThread(threadId) {
  openDialog('rename', threadId)
}

function removeThread(threadId) {
  openDialog('delete', threadId)
}

function closeDialog() {
  if (dialogBusy.value) {
    return
  }
  dialog.value = null
  restoreDialogFocus()
}

function onDialogEnter(event) {
  if (event.isComposing) {
    return
  }
  event.preventDefault()
  confirmDialog()
}

async function confirmDialog() {
  if (!dialog.value || dialogBusy.value) {
    return
  }
  const { kind, threadId } = dialog.value

  if (kind === 'rename') {
    const title = dialogInput.value.trim()
    if (!title || title.length > 60) {
      dialogError.value = 'スレッド名は1〜60文字で入力してください。'
      return
    }
    dialogBusy.value = true
    try {
      await chat.renameThread(threadId, title)
      dialog.value = null
      restoreDialogFocus()
    } catch (error) {
      if (handleAuthError(error)) {
        return
      }
      dialogError.value = error.message && toFriendlyErrorMessage(error.message) === error.message
        ? error.message
        : 'スレッド名を変更できませんでした。少し待ってからもう一度お試しください。'
    } finally {
      dialogBusy.value = false
    }
    return
  }

  const wasCurrent = threadId === chat.threadId || threadId === route.params.threadId
  dialogBusy.value = true
  try {
    await chat.deleteThread(threadId)
    dialog.value = null
    restoreDialogFocus()
    closeDrawer()
    if (wasCurrent) {
      router.replace('/chat')
    }
  } catch (error) {
    if (handleAuthError(error)) {
      return
    }
    dialogError.value = error.message && toFriendlyErrorMessage(error.message) === error.message
      ? error.message
      : '会話を削除できませんでした。少し待ってからもう一度お試しください。'
  } finally {
    dialogBusy.value = false
  }
}

async function retryLastMessage() {
  try {
    await chat.retryLast()
  } catch (error) {
    handleAuthError(error)
  } finally {
    await nextTick()
    inputRef.value?.focus()
  }
}

function onWindowKeydown(event) {
  if (event.key !== 'Escape') {
    return
  }
  if (dialog.value) {
    closeDialog()
    return
  }
  if (drawerOpen.value) {
    closeDrawer()
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
  () => chat.messages.map((message) => messageSourceKey(message)),
  (keys) => {
    const currentKeys = new Set(keys)
    const nextKeys = new Set(
      [...expandedSourceKeys.value].filter((key) => currentKeys.has(key)),
    )
    if (nextKeys.size !== expandedSourceKeys.value.size) {
      expandedSourceKeys.value = nextKeys
    }
  },
)

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
  window.addEventListener('keydown', onWindowKeydown)
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
  window.removeEventListener('keydown', onWindowKeydown)
  footerResizeObserver?.disconnect()
  if (busyHintTimer) {
    window.clearTimeout(busyHintTimer)
  }
})
</script>

<template>
  <div class="chat-shell flex h-dvh overflow-hidden text-white">
    <aside class="hidden w-[17.5rem] shrink-0 border-r border-edge lg:block">
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
      :inert="!drawerOpen"
    >
      <div
        class="drawer-scrim absolute inset-0 bg-black/70 backdrop-blur-[2px]"
        :class="drawerOpen ? 'opacity-100' : 'opacity-0'"
        @click="closeDrawer"
      ></div>
      <aside
        class="drawer-panel absolute inset-y-0 left-0 w-[17.5rem] max-w-[88vw] transform border-r border-edge shadow-glass"
        :class="drawerOpen ? 'translate-x-0' : '-translate-x-full'"
      >
        <ThreadSidebar
          :threads="chat.threads"
          :current-thread-id="chat.threadId"
          :disabled="chat.isSending"
          :user-name="auth.user?.name || ''"
          nav-label="会話履歴（ドロワー）"
          @select="selectThread"
          @new-chat="startNewChat"
          @rename="renameThread"
          @delete="removeThread"
          @logout="logout"
        />
      </aside>
    </div>

    <main class="flex h-full min-w-0 flex-1 flex-col overflow-y-auto">
      <header class="sticky top-0 z-20 border-b border-edge bg-ink-base/[0.88] backdrop-blur-xl">
        <div class="mx-auto flex min-h-[68px] max-w-3xl items-center gap-3 px-4 py-2.5">
          <button
            type="button"
            class="grid h-11 w-11 shrink-0 place-items-center rounded-ui-sm text-white/60 transition duration-fast ease-standard hover:bg-fill-hover hover:text-white active:scale-[0.97] lg:hidden"
            aria-label="会話履歴を開く"
            @click="drawerOpen = true"
          >
            <svg aria-hidden="true" class="h-5 w-5" viewBox="0 0 24 24" fill="none">
              <path d="M4 6h16M4 12h16M4 18h16" stroke="currentColor" stroke-width="2" stroke-linecap="round" />
            </svg>
          </button>
          <div class="flex min-w-0 items-center gap-3 lg:hidden">
            <img src="/app-icon.png" alt="" class="h-9 w-9 rounded-ui-sm shadow-soft" />
            <div class="min-w-0">
              <h1 class="truncate text-sm font-semibold tracking-[-0.015em]">本荘キャンパス案内 AI</h1>
              <p class="font-display mt-0.5 truncate text-[9px] font-medium uppercase tracking-[0.15em] text-white/40">Akita Prefectural University</p>
            </div>
          </div>
          <div class="hidden w-full items-center justify-between gap-6 lg:flex">
            <div class="flex items-center gap-3">
              <span class="h-1.5 w-1.5 rounded-full bg-brand-signal" aria-hidden="true"></span>
              <h1 class="font-display text-[10px] font-semibold uppercase tracking-[0.2em] text-white/70">Campus desk / online</h1>
            </div>
            <p class="font-display text-[10px] font-medium uppercase tracking-[0.18em] text-white/35">Honjo / OC 2026</p>
          </div>
        </div>
      </header>

      <section class="flex w-full flex-1 flex-col pt-2 sm:pt-4">
        <div
          class="flex flex-1 flex-col"
          :style="{ paddingBottom: chat.messages.length ? `${footerClearancePx}px` : '0px' }"
        >
          <div
            v-if="chat.messages.length === 0"
            class="relative mx-auto flex w-full max-w-3xl flex-1 flex-col justify-center px-5 py-8 sm:px-4 sm:py-12"
          >
            <div class="chat-empty__identity flex items-center gap-3">
              <img src="/app-icon.png" alt="" class="h-10 w-10 rounded-ui-sm shadow-soft" />
              <div>
                <p class="font-display text-[10px] font-semibold uppercase tracking-[0.2em] text-white/65">Ask Honjo</p>
                <p class="mt-0.5 text-xs text-white/40">あなたのキャンパス案内デスク</p>
              </div>
            </div>

            <h2 class="chat-empty__heading mt-6 max-w-2xl text-[clamp(2rem,5vw,3.6rem)] font-semibold leading-[1.12] tracking-[-0.05em] text-white/90">
              <span class="block">こんにちは、</span>
              <span v-if="auth.user?.name" class="aurora-copy">{{ auth.user.name }} さん。</span>
              <span v-else>ようこそ。</span>
            </h2>

            <div class="chat-empty__support mt-5 flex flex-col items-start gap-4 sm:flex-row sm:items-center sm:justify-between">
              <p class="text-[15px] leading-7 text-white/55">学科、施設、アクセス。気になることからどうぞ。</p>
              <p
                v-if="countdownLabel"
                class="countdown-chip inline-flex min-h-11 shrink-0 items-center gap-2.5 rounded-full px-4 py-2 text-xs font-medium text-white/75"
              >
                <span class="h-1.5 w-1.5 rounded-full bg-brand-signal" aria-hidden="true"></span>
                {{ countdownLabel }}
              </p>
            </div>

            <div class="chat-empty__actions mt-8 grid w-full gap-2.5 sm:grid-cols-2">
              <button
                v-for="(suggestion, index) in suggestions"
                :key="suggestion"
                type="button"
                class="suggestion-card group flex min-h-16 items-center gap-4 rounded-ui border border-edge bg-ink-surface/75 px-4 py-3 text-left text-sm text-white/75 shadow-hairline transition duration-base ease-expressive hover:-translate-y-0.5 hover:border-edge-strong hover:bg-ink-raised hover:text-white active:translate-y-0 active:scale-[0.985]"
                @click="applySuggestion(suggestion)"
              >
                <span class="font-display text-[10px] font-semibold tracking-[0.16em] text-white/40 transition duration-base ease-standard group-hover:text-brand-soft">
                  {{ String(index + 1).padStart(2, '0') }}
                </span>
                <span class="flex-1">{{ suggestion }}</span>
              </button>
            </div>
          </div>

          <TransitionGroup v-else appear name="message-list" tag="div" class="space-y-8 py-6 sm:py-8">
            <article
              v-for="message in chat.messages"
              :key="message.clientId || message.id"
              class="message-row w-full px-4"
              :class="message.role === 'user' ? 'message-row--user' : 'message-row--assistant'"
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
                        <button
                          type="button"
                          class="group flex min-h-11 w-full items-center justify-between gap-3 rounded-ui-sm px-3 py-1 text-left transition duration-base ease-standard hover:bg-fill-hover active:scale-[0.99]"
                          :aria-expanded="isSourcesExpanded(message)"
                          :aria-controls="sourceRegionId(message)"
                          :aria-label="sourcesToggleLabel(message)"
                          @click="toggleSources(message)"
                        >
                          <span class="flex min-w-0 items-baseline gap-2">
                            <span class="text-xs font-medium tracking-wide text-white/55">出典</span>
                            <span class="text-xs text-white/40">{{ message.sources.length }}件</span>
                          </span>
                          <svg
                            aria-hidden="true"
                            class="sources-disclosure-icon h-4 w-4 shrink-0 text-white/40 transition duration-base ease-standard group-hover:text-white/70"
                            :class="isSourcesExpanded(message) ? 'rotate-180' : 'rotate-0'"
                            viewBox="0 0 24 24"
                            fill="none"
                          >
                            <path d="M6 9l6 6 6-6" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round" />
                          </svg>
                        </button>
                        <Transition name="sources-collapse">
                          <div
                            v-show="isSourcesExpanded(message)"
                            :id="sourceRegionId(message)"
                            role="region"
                            :aria-label="sourcesRegionLabel(message)"
                            class="pt-2"
                          >
                            <ul class="flex flex-wrap gap-2">
                              <li v-for="source in message.sources" :key="source.url">
                                <a
                                  class="group flex min-h-11 items-center gap-2 rounded-ui-sm border border-edge bg-ink-surface py-2 pl-2 pr-3 text-xs text-white/70 transition duration-base ease-standard hover:border-edge-strong hover:bg-ink-raised hover:text-white"
                                  :href="source.url"
                                  target="_blank"
                                  rel="noreferrer"
                                >
                                  <span
                                    class="inline-flex shrink-0 items-center gap-1 rounded-full border border-white/10 bg-white/[0.045] px-2 py-0.5 text-[10px] font-semibold text-white/60"
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
                                    class="h-3 w-3 shrink-0 text-white/30 transition duration-base ease-standard group-hover:text-white/70"
                                    viewBox="0 0 24 24"
                                    fill="none"
                                  >
                                    <path d="M14 5h5v5 M19 5l-9 9 M11 5H6a1 1 0 0 0-1 1v12a1 1 0 0 0 1 1h12a1 1 0 0 0 1-1v-5" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" />
                                  </svg>
                                </a>
                              </li>
                            </ul>
                          </div>
                        </Transition>
                      </div>
                    </div>
                  </LoadingSpinnerV5>
                </div>
              </template>
              <div v-else class="flex justify-end">
                <p class="max-w-[88%] whitespace-pre-wrap break-words rounded-[1.35rem] rounded-br-md border border-white/[0.075] bg-ink-high px-4 py-2.5 text-base leading-7 text-[#f1f1ec] shadow-soft sm:max-w-[78%]">
                  {{ message.content }}
                </p>
              </div>
            </div>
            </article>
          </TransitionGroup>
          <div ref="messagesEnd" :style="{ scrollMarginBottom: `${footerClearancePx}px` }"></div>
        </div>

        <form
          ref="footerRef"
          class="composer-dock sticky bottom-0 z-10 px-4 pb-[calc(0.75rem_+_env(safe-area-inset-bottom))] pt-8"
          @submit.prevent="send"
        >
          <div class="mx-auto w-full max-w-3xl">
            <div
              class="composer-shell flex items-end gap-2 rounded-[1.6rem] p-2"
              :class="{ 'composer-shell--streaming': chat.isSending }"
            >
              <textarea
                ref="inputRef"
                v-model="draft"
                rows="1"
                class="max-h-[164px] min-h-11 flex-1 resize-none bg-transparent px-3 py-2.5 text-base leading-6 text-white outline-none placeholder:text-white/45 focus-visible:outline-none"
                placeholder="質問を入力"
                @keydown.enter="onEnter"
              ></textarea>
              <button
                type="submit"
                class="grid h-11 w-11 shrink-0 place-items-center rounded-full text-[#11130f] transition duration-base ease-expressive enabled:bg-ink-paper enabled:hover:-translate-y-0.5 enabled:hover:bg-white enabled:active:translate-y-0 enabled:active:scale-[0.94] disabled:cursor-not-allowed disabled:bg-white/[0.07] disabled:text-white/25"
                :disabled="!draft.trim() || chat.isSending"
                aria-label="送信"
              >
                <svg aria-hidden="true" class="h-5 w-5" viewBox="0 0 24 24" fill="none">
                  <path d="M12 19V5M5 12l7-7 7 7" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" />
                </svg>
              </button>
            </div>
            <!-- The full error message lives in the conversation bubble; this
                 banner is a compact retry affordance. -->
            <div
              v-if="chat.error"
              class="mt-2 flex min-h-11 items-center gap-2.5 rounded-ui-sm border border-red-400/25 bg-red-500/10 px-3 py-2 text-sm text-red-200"
              role="alert"
            >
              <svg aria-hidden="true" class="h-4 w-4 shrink-0" viewBox="0 0 24 24" fill="none">
                <path d="M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18z M12 8v5 M12 16.5h.01" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" />
              </svg>
              <span class="min-w-0 flex-1">回答を受け取れませんでした</span>
              <button
                v-if="chat.lastFailedMessage"
                type="button"
                class="min-h-11 shrink-0 rounded-ui-sm border border-red-300/35 px-3 py-2 text-xs font-medium text-red-100 transition duration-fast ease-standard hover:bg-red-400/15 active:scale-[0.97] disabled:cursor-not-allowed disabled:opacity-50"
                :disabled="chat.isSending"
                @click="retryLastMessage"
              >
                再試行
              </button>
            </div>
            <Transition name="dialog-fade">
              <p
                v-if="busyHint"
                class="mt-2 flex min-h-11 items-center gap-2 rounded-ui-sm border border-brand-signal/25 bg-brand-signal/[0.08] px-3 py-2 text-sm text-[#ffb29e]"
                role="status"
              >
                <svg aria-hidden="true" class="h-4 w-4 shrink-0" viewBox="0 0 24 24" fill="none">
                  <path d="M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18z M12 7.5V12l3 2" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" />
                </svg>
                {{ busyHint }}
              </p>
            </Transition>
            <p class="font-display mt-2 hidden text-center text-[10px] tracking-[0.06em] text-white/35 sm:block">
              Enter で送信 ・ Shift + Enter で改行
            </p>
          </div>
        </form>
      </section>
    </main>

    <Transition name="dialog-fade">
      <div
        v-if="dialog"
        class="fixed inset-0 z-50 flex items-end justify-center p-4 pb-[calc(1rem_+_env(safe-area-inset-bottom))] sm:items-center sm:pb-4"
        role="dialog"
        aria-modal="true"
        :aria-label="dialog.kind === 'rename' ? 'スレッド名を変更' : '会話を削除'"
      >
        <div class="absolute inset-0 bg-black/70 backdrop-blur-[2px]" @click="closeDialog"></div>
        <div class="dialog-panel relative w-full max-w-sm rounded-ui-lg border border-edge-strong bg-ink-raised p-5 shadow-glass">
          <template v-if="dialog.kind === 'rename'">
            <p class="font-display text-[9px] font-semibold uppercase tracking-[0.2em] text-brand-soft">Edit conversation</p>
            <h3 class="mt-2 text-lg font-semibold tracking-[-0.025em]">スレッド名を変更</h3>
            <input
              ref="dialogInputRef"
              v-model="dialogInput"
              class="mt-4 min-h-11 w-full rounded-ui-sm border border-edge-strong bg-ink-surface px-3.5 py-2.5 text-sm text-white outline-none transition duration-base ease-standard placeholder:text-white/45 focus:border-white/30"
              placeholder="スレッド名（1〜60文字）"
              maxlength="61"
              @keydown.enter="onDialogEnter"
            />
          </template>
          <template v-else>
            <p class="font-display text-[9px] font-semibold uppercase tracking-[0.2em] text-red-300/75">Delete conversation</p>
            <h3 class="mt-2 text-lg font-semibold tracking-[-0.025em]">会話を削除しますか？</h3>
            <p class="mt-2 break-words text-sm leading-6 text-white/60">
              「{{ dialog.threadTitle }}」を削除すると元に戻せません。
            </p>
          </template>
          <p v-if="dialogError" class="mt-3 text-sm text-red-300" role="alert">{{ dialogError }}</p>
          <div class="mt-5 flex justify-end gap-2">
            <button
              ref="dialogCancelRef"
              type="button"
              class="min-h-11 rounded-ui-sm border border-edge px-4 py-2 text-sm text-white/70 transition duration-fast ease-standard hover:bg-fill-hover hover:text-white active:scale-[0.97] disabled:cursor-not-allowed disabled:opacity-50"
              :disabled="dialogBusy"
              @click="closeDialog"
            >
              キャンセル
            </button>
            <button
              type="button"
              class="min-h-11 rounded-ui-sm px-4 py-2 text-sm font-semibold transition duration-fast ease-standard active:scale-[0.97] disabled:cursor-not-allowed disabled:opacity-60"
              :class="dialog.kind === 'rename'
                ? 'bg-ink-paper text-[#10120f] hover:bg-white'
                : 'bg-red-500 text-white hover:bg-red-400'"
              :disabled="dialogBusy"
              @click="confirmDialog"
            >
              {{ dialogBusy ? '処理中…' : dialog.kind === 'rename' ? '変更する' : '削除する' }}
            </button>
          </div>
        </div>
      </div>
    </Transition>
  </div>
</template>

<style scoped>
.sources-collapse-enter-active,
.sources-collapse-leave-active {
  transition:
    opacity var(--motion-base) ease-out,
    transform var(--motion-base) var(--ease-expressive);
}

.sources-collapse-enter-from,
.sources-collapse-leave-to {
  opacity: 0;
  transform: translateY(-0.25rem);
}

@media (prefers-reduced-motion: reduce) {
  .sources-collapse-enter-active,
  .sources-collapse-leave-active,
  .sources-disclosure-icon {
    transition: none !important;
  }

  .sources-collapse-enter-from,
  .sources-collapse-leave-to {
    opacity: 1;
    transform: none;
  }
}
</style>

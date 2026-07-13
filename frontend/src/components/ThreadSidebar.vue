<script setup>
import { computed, ref } from 'vue'

const props = defineProps({
  threads: {
    type: Array,
    default: () => [],
  },
  currentThreadId: {
    type: String,
    default: null,
  },
  disabled: {
    type: Boolean,
    default: false,
  },
  userName: {
    type: String,
    default: '',
  },
})

const emit = defineEmits(['select', 'new-chat', 'rename', 'delete', 'logout'])

const openMenuId = ref(null)

const userInitial = computed(() => (props.userName ? Array.from(props.userName)[0] : '?'))

function toggleMenu(threadId) {
  openMenuId.value = openMenuId.value === threadId ? null : threadId
}

function closeMenu() {
  openMenuId.value = null
}

function onRename(threadId) {
  closeMenu()
  emit('rename', threadId)
}

function onDelete(threadId) {
  closeMenu()
  emit('delete', threadId)
}
</script>

<template>
  <div class="flex h-full min-h-0 flex-col bg-ink-surface text-white">
    <div class="p-3">
      <button
        type="button"
        class="flex min-h-11 w-full items-center gap-2.5 rounded-xl border border-edge bg-fill-hover px-3.5 py-2.5 text-sm font-medium text-white/85 transition duration-200 ease-out hover:border-edge-strong hover:bg-fill-active hover:text-white active:scale-[0.98] disabled:cursor-not-allowed disabled:opacity-45"
        :disabled="disabled"
        @click="emit('new-chat')"
      >
        <svg aria-hidden="true" class="h-4 w-4 shrink-0" viewBox="0 0 24 24" fill="none">
          <path d="M12 5v14M5 12h14" stroke="currentColor" stroke-width="2" stroke-linecap="round" />
        </svg>
        新しい会話
      </button>
    </div>

    <nav class="flex-1 overflow-y-auto px-2 pb-3" aria-label="会話履歴">
      <p class="px-3.5 pb-1.5 pt-1 text-[11px] font-medium tracking-wider text-white/35">会話履歴</p>
      <p v-if="threads.length === 0" class="px-3.5 pt-1 text-xs leading-5 text-white/40">
        まだ会話がありません。
      </p>
      <ul v-else class="space-y-0.5">
        <li v-for="thread in threads" :key="thread.id" class="group relative">
          <button
            type="button"
            class="relative flex min-h-11 w-full items-center rounded-xl py-2 pl-3.5 pr-10 text-left text-sm transition duration-150 ease-out disabled:cursor-not-allowed disabled:opacity-45"
            :class="thread.id === currentThreadId
              ? 'bg-fill-active text-white'
              : 'text-white/65 hover:bg-fill-hover hover:text-white'"
            :disabled="disabled"
            :aria-current="thread.id === currentThreadId ? 'page' : undefined"
            @click="emit('select', thread.id)"
          >
            <span
              v-if="thread.id === currentThreadId"
              class="absolute left-1 top-1/2 h-5 w-[3px] -translate-y-1/2 rounded-full bg-gradient-to-b from-brand-coral via-brand-sun to-brand-mint"
              aria-hidden="true"
            ></span>
            <span class="truncate">{{ thread.title }}</span>
          </button>
          <button
            type="button"
            class="absolute right-1 top-1/2 grid h-8 w-8 -translate-y-1/2 place-items-center rounded-lg text-white/55 transition duration-150 ease-out hover:bg-fill-active hover:text-white disabled:cursor-not-allowed lg:opacity-0 lg:focus:opacity-100 lg:group-hover:opacity-100"
            :class="openMenuId === thread.id ? 'bg-fill-active text-white lg:opacity-100' : ''"
            :disabled="disabled"
            :aria-label="`「${thread.title}」のメニュー`"
            aria-haspopup="menu"
            :aria-expanded="openMenuId === thread.id"
            @click.stop="toggleMenu(thread.id)"
          >
            <svg aria-hidden="true" class="h-4 w-4" viewBox="0 0 24 24" fill="currentColor">
              <circle cx="5" cy="12" r="1.7" />
              <circle cx="12" cy="12" r="1.7" />
              <circle cx="19" cy="12" r="1.7" />
            </svg>
          </button>
          <div
            v-if="openMenuId === thread.id"
            role="menu"
            class="absolute right-1 top-full z-30 mt-1 w-44 overflow-hidden rounded-xl border border-edge-strong bg-ink-raised py-1 shadow-glass"
          >
            <button
              type="button"
              role="menuitem"
              class="flex w-full items-center gap-2.5 px-3 py-2.5 text-left text-sm text-white/80 transition duration-150 ease-out hover:bg-fill-hover hover:text-white"
              @click="onRename(thread.id)"
            >
              <svg aria-hidden="true" class="h-4 w-4 shrink-0" viewBox="0 0 24 24" fill="none">
                <path d="M4 20h4L19.5 8.5a2.1 2.1 0 0 0-3-3L5 17v3z M13.5 6.5l3 3" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" />
              </svg>
              名前を変更
            </button>
            <button
              type="button"
              role="menuitem"
              class="flex w-full items-center gap-2.5 px-3 py-2.5 text-left text-sm text-red-300 transition duration-150 ease-out hover:bg-red-500/10"
              @click="onDelete(thread.id)"
            >
              <svg aria-hidden="true" class="h-4 w-4 shrink-0" viewBox="0 0 24 24" fill="none">
                <path d="M4 7h16 M9 7V5a1 1 0 0 1 1-1h4a1 1 0 0 1 1 1v2 M6.5 7l.8 12a2 2 0 0 0 2 1.9h5.4a2 2 0 0 0 2-1.9l.8-12 M10 11v6 M14 11v6" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" />
              </svg>
              削除
            </button>
          </div>
        </li>
      </ul>
    </nav>

    <div class="border-t border-edge p-3">
      <div class="flex items-center gap-3 rounded-xl px-1.5 py-1.5">
        <span
          class="grid h-9 w-9 shrink-0 place-items-center rounded-full bg-gradient-to-br from-brand-coral via-brand-sun to-brand-mint text-sm font-bold text-[#101217]"
          aria-hidden="true"
        >
          {{ userInitial }}
        </span>
        <div class="min-w-0 flex-1">
          <p class="truncate text-sm font-medium text-white/90">{{ userName }}</p>
          <p class="truncate text-[11px] text-white/40">オープンキャンパス2026</p>
        </div>
        <button
          type="button"
          class="grid h-10 w-10 shrink-0 place-items-center rounded-lg text-white/55 transition duration-150 ease-out hover:bg-fill-hover hover:text-white active:scale-[0.97]"
          title="ログアウト"
          aria-label="ログアウト"
          @click="emit('logout')"
        >
          <svg aria-hidden="true" class="h-[18px] w-[18px]" viewBox="0 0 24 24" fill="none">
            <path d="M15 4h3a2 2 0 0 1 2 2v12a2 2 0 0 1-2 2h-3 M10 8l-4 4 4 4 M6 12h10" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" />
          </svg>
        </button>
      </div>
    </div>

    <!-- Invisible click-catcher so an open item menu closes on outside click. -->
    <div v-if="openMenuId" class="fixed inset-0 z-20" aria-hidden="true" @click="closeMenu"></div>
  </div>
</template>

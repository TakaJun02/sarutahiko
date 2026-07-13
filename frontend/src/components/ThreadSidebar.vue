<script setup>
import { ref } from 'vue'

defineProps({
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
  <div class="flex h-full min-h-0 flex-col bg-[#0c0e12] text-white">
    <div class="p-3">
      <button
        type="button"
        class="flex w-full items-center gap-2 rounded-xl border border-white/10 bg-white/[0.04] px-3 py-2.5 text-sm text-white/85 transition hover:border-white/24 hover:bg-white/[0.08] disabled:cursor-not-allowed disabled:opacity-45"
        :disabled="disabled"
        @click="emit('new-chat')"
      >
        <svg aria-hidden="true" class="h-4 w-4" viewBox="0 0 24 24" fill="none">
          <path d="M12 5v14M5 12h14" stroke="currentColor" stroke-width="2" stroke-linecap="round" />
        </svg>
        新しい会話
      </button>
    </div>

    <nav class="flex-1 overflow-y-auto px-2 pb-3" aria-label="会話履歴">
      <p v-if="threads.length === 0" class="px-3 pt-1 text-xs text-white/40">まだ会話がありません。</p>
      <ul v-else class="space-y-0.5">
        <li v-for="thread in threads" :key="thread.id" class="group relative">
          <button
            type="button"
            class="block w-full truncate rounded-lg py-2 pl-3 pr-9 text-left text-sm transition disabled:cursor-not-allowed disabled:opacity-45"
            :class="thread.id === currentThreadId
              ? 'bg-white/12 text-white'
              : 'text-white/68 hover:bg-white/[0.06] hover:text-white'"
            :disabled="disabled"
            :aria-current="thread.id === currentThreadId ? 'page' : undefined"
            @click="emit('select', thread.id)"
          >
            {{ thread.title }}
          </button>
          <button
            type="button"
            class="absolute right-1.5 top-1/2 grid h-7 w-7 -translate-y-1/2 place-items-center rounded-md text-white/55 transition hover:bg-white/12 hover:text-white lg:opacity-0 lg:focus:opacity-100 lg:group-hover:opacity-100 disabled:cursor-not-allowed"
            :class="openMenuId === thread.id ? 'bg-white/12 text-white lg:opacity-100' : ''"
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
            class="absolute right-1 top-full z-30 mt-1 w-40 overflow-hidden rounded-xl border border-white/12 bg-[#171a21] py-1 shadow-glass"
          >
            <button
              type="button"
              role="menuitem"
              class="block w-full px-3 py-2 text-left text-sm text-white/80 transition hover:bg-white/[0.08] hover:text-white"
              @click="onRename(thread.id)"
            >
              名前を変更
            </button>
            <button
              type="button"
              role="menuitem"
              class="block w-full px-3 py-2 text-left text-sm text-red-300 transition hover:bg-white/[0.08]"
              @click="onDelete(thread.id)"
            >
              削除
            </button>
          </div>
        </li>
      </ul>
    </nav>

    <div class="flex items-center justify-between gap-2 border-t border-white/8 p-3">
      <p class="min-w-0 flex-1 truncate text-sm text-white/70">{{ userName }}</p>
      <button
        type="button"
        class="shrink-0 rounded-full border border-white/10 px-3 py-1.5 text-xs text-white/68 transition hover:border-white/24 hover:text-white"
        @click="emit('logout')"
      >
        ログアウト
      </button>
    </div>

    <!-- Invisible click-catcher so an open item menu closes on outside click. -->
    <div v-if="openMenuId" class="fixed inset-0 z-20" aria-hidden="true" @click="closeMenu"></div>
  </div>
</template>

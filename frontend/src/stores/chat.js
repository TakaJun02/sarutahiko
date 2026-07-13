import { defineStore } from 'pinia'

import {
  ApiError,
  deleteThreadRequest,
  fetchThread,
  fetchThreads,
  getStoredToken,
  renameThreadRequest,
} from '../services/api'

export function createMessage(role, content = '', overrides = {}) {
  const id = overrides.id || crypto.randomUUID()
  return {
    id,
    clientId: overrides.clientId || id,
    role,
    content,
    pending: false,
    streaming: false,
    statusText: '',
    statusStep: '',
    sources: [],
    ...overrides,
  }
}

export function parseSseBlock(block) {
  const lines = block.split(/\r?\n/)
  let event = 'message'
  const dataLines = []
  for (const line of lines) {
    if (line.startsWith('event:')) {
      event = line.slice(6).trim()
    } else if (line.startsWith('data:')) {
      dataLines.push(line.slice(5).trimStart())
    }
  }
  if (!dataLines.length) {
    return null
  }
  return {
    event,
    data: JSON.parse(dataLines.join('\n')),
  }
}

export function applyAssistantEvent(message, event) {
  if (event.event === 'status') {
    message.statusText = event.data.text
    message.statusStep = event.data.step
    message.pending = true
    message.streaming = false
    return
  }
  if (event.event === 'token') {
    message.pending = false
    message.streaming = true
    message.content += event.data.text
    return
  }
  if (event.event === 'done') {
    message.pending = false
    message.streaming = false
    message.id = event.data.message_id || message.id
    message.sources = event.data.sources || []
    return event.data.thread_id
  }
  if (event.event === 'error') {
    message.pending = false
    message.streaming = false
    message.content = event.data.message || '回答生成中にエラーが発生しました。'
  }
}

export const useChatStore = defineStore('chat', {
  state: () => ({
    messages: [],
    threadId: null,
    threads: [],
    isSending: false,
    error: '',
  }),
  actions: {
    reset() {
      this.messages = []
      this.threadId = null
      this.threads = []
      this.isSending = false
      this.error = ''
    },
    newChat() {
      this.messages = []
      this.threadId = null
      this.error = ''
    },
    async loadThreads() {
      this.threads = await fetchThreads()
    },
    async openThread(threadId) {
      const payload = await fetchThread(threadId)
      this.threadId = payload.thread.id
      this.messages = payload.messages.map((message) =>
        createMessage(message.role, message.content, {
          id: message.id,
          pending: false,
          streaming: false,
          sources: message.sources || [],
        }),
      )
      this.error = ''
    },
    async renameThread(threadId, title) {
      const updated = await renameThreadRequest(threadId, title)
      const index = this.threads.findIndex((thread) => thread.id === threadId)
      if (index !== -1) {
        this.threads.splice(index, 1, { ...this.threads[index], ...updated })
      }
    },
    async deleteThread(threadId) {
      await deleteThreadRequest(threadId)
      this.threads = this.threads.filter((thread) => thread.id !== threadId)
      if (this.threadId === threadId) {
        this.newChat()
      }
    },
    async sendMessage(text) {
      const messageText = text.trim()
      if (!messageText || this.isSending) {
        return
      }

      const userMessage = createMessage('user', messageText)
      const assistantDraft = createMessage('assistant', '', {
        pending: true,
        statusText: '質問を分析しています…',
        statusStep: 'analyze',
      })
      this.messages.push(userMessage, assistantDraft)
      const assistantMessage = this.messages[this.messages.length - 1]
      this.isSending = true
      this.error = ''

      try {
        await this.streamChatResponse(messageText, assistantMessage)
        if (this.threadId) {
          // Refresh the sidebar so new threads appear first and existing
          // threads bubble up (updated_at descending on the server).
          try {
            await this.loadThreads()
          } catch {
            // A stale sidebar is not worth failing the whole send for.
          }
        }
      } catch (error) {
        assistantMessage.pending = false
        assistantMessage.streaming = false
        if (error.status === 401) {
          throw error
        }
        this.error = error.message || '回答を取得できませんでした。'
        assistantMessage.content = this.error
      } finally {
        this.isSending = false
      }
    },
    async streamChatResponse(text, assistantMessage) {
      const token = getStoredToken()
      const response = await fetch('/api/chat', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          ...(token ? { Authorization: `Bearer ${token}` } : {}),
        },
        body: JSON.stringify({
          message: text,
          thread_id: this.threadId,
        }),
      })

      if (!response.ok) {
        let detail = response.statusText
        try {
          const body = await response.json()
          detail = body.detail || detail
        } catch {
          // Keep response status text if the error body is not JSON.
        }
        throw new ApiError(detail, response.status)
      }
      if (!response.body) {
        throw new ApiError('SSE ストリームを開始できませんでした。', response.status)
      }

      const reader = response.body.getReader()
      const decoder = new TextDecoder()
      let buffer = ''

      while (true) {
        const { value, done } = await reader.read()
        if (done) {
          break
        }
        buffer += decoder.decode(value, { stream: true })
        buffer = this.consumeSseBuffer(buffer, assistantMessage)
      }

      buffer += decoder.decode()
      this.consumeSseBuffer(buffer, assistantMessage, true)
    },
    consumeSseBuffer(buffer, assistantMessage, flush = false) {
      const normalized = buffer.replace(/\r\n/g, '\n')
      const blocks = normalized.split('\n\n')
      const incomplete = flush ? '' : blocks.pop() || ''
      const completeBlocks = flush ? blocks.filter(Boolean) : blocks

      for (const block of completeBlocks) {
        if (!block.trim()) {
          continue
        }
        const parsed = parseSseBlock(block)
        if (!parsed) {
          continue
        }
        const threadId = applyAssistantEvent(assistantMessage, parsed)
        if (threadId) {
          this.threadId = threadId
        }
      }

      return incomplete
    },
  },
})

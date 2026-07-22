import { defineStore } from 'pinia'

import {
  ApiError,
  deleteThreadRequest,
  fetchThread,
  fetchThreads,
  getStoredToken,
  renameThreadRequest,
} from '../services/api'
import { advanceRevealCount } from '../utils/revealPacing'

const FRIENDLY_SEND_ERROR = 'うまく接続できませんでした。少し待ってからもう一度お試しください。'
const REDUCED_MOTION_QUERY = '(prefers-reduced-motion: reduce)'

let revealRafId = null
let revealLastTimestamp = null
let revealStore = null
let revealListenersInstalled = false
let reducedMotionQuery = null
let documentWasHidden = false

// Backend "detail" strings are written in Japanese guide tone; anything else
// (raw HTTP status texts such as "Internal Server Error") is replaced with a
// friendly message so visitors never see bare English errors.
export function toFriendlyErrorMessage(message) {
  // CJK punctuation / kana / kanji ranges (U+3000-30FF, U+3400-9FFF).
  if (typeof message === 'string' && /[\u3000-\u30ff\u3400-\u9fff]/.test(message)) {
    return message
  }
  return FRIENDLY_SEND_ERROR
}

export function createMessage(role, content = '', overrides = {}) {
  const id = overrides.id || crypto.randomUUID()
  const message = {
    id,
    clientId: overrides.clientId || id,
    role,
    content,
    pending: false,
    streaming: false,
    statusText: '',
    statusStep: '',
    statusPartial: false,
    statusRunId: 0,
    sources: [],
    map: null,
    mapInteractive: false,
    clarificationExpected: false,
    clarificationActive: false,
    ...overrides,
  }
  if (typeof message.revealedLength !== 'number') {
    message.revealedLength = message.content.length
  }
  return message
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
    const incomingText = String(event.data.text || '')
    const incomingStep = String(event.data.step || '')
    const currentText = String(message.statusText || '')
    const currentStep = String(message.statusStep || '')
    const withoutTrailingEllipsis = (text) => text.endsWith('…') ? text.slice(0, -1) : text
    const extendsCurrentRun = (
      incomingStep === currentStep
      && withoutTrailingEllipsis(incomingText).startsWith(withoutTrailingEllipsis(currentText))
    )
    if (!extendsCurrentRun) {
      message.statusRunId = (message.statusRunId || 0) + 1
    }
    message.statusText = incomingText
    message.statusStep = incomingStep
    message.statusPartial = event.data.partial === true
    message.pending = true
    message.streaming = false
    if (incomingStep === 'clarify') {
      message.clarificationExpected = true
    }
    return
  }
  if (event.event === 'token') {
    message.pending = false
    message.streaming = true
    message.content += event.data.text
    return
  }
  if (event.event === 'map') {
    message.finalMap = event.data
    message.finalMapInteractive = event.data.mode === 'ask_origin'
    return
  }
  if (event.event === 'done') {
    message.pending = false
    message.streaming = true
    message.id = event.data.message_id || message.id
    message.doneReceived = true
    message.finalSources = event.data.sources || []
    message.finalClarification = event.data.kind === 'clarification'
    return event.data.thread_id
  }
  if (event.event === 'error') {
    message.pending = false
    message.streaming = false
    message.content = event.data.message || '回答生成中にエラーが発生しました。'
    message.revealedLength = message.content.length
    message.sources = []
    message.map = null
    message.mapInteractive = false
    message.clarificationExpected = false
    message.clarificationActive = false
    delete message.doneReceived
    delete message.finalSources
    delete message.finalMap
    delete message.finalMapInteractive
    delete message.finalClarification
  }
}

function getReducedMotionQuery() {
  if (typeof window === 'undefined' || typeof window.matchMedia !== 'function') {
    return null
  }
  if (!reducedMotionQuery) {
    reducedMotionQuery = window.matchMedia(REDUCED_MOTION_QUERY)
  }
  return reducedMotionQuery
}

function isRevealPacingDisabled() {
  return getReducedMotionQuery()?.matches === true
}

function clampMessageReveal(message) {
  const total = message.content.length
  if (typeof message.revealedLength !== 'number') {
    message.revealedLength = total
  } else if (message.revealedLength > total) {
    message.revealedLength = total
  } else if (message.revealedLength < 0) {
    message.revealedLength = 0
  }
}

function finalizeAssistantMessage(message) {
  message.streaming = false
  message.sources = message.finalSources || []
  message.map = message.finalMap || null
  message.mapInteractive = Boolean(message.finalMapInteractive)
  message.clarificationActive = Boolean(message.finalClarification)
  message.clarificationExpected = Boolean(message.finalClarification)
  delete message.doneReceived
  delete message.finalSources
  delete message.finalMap
  delete message.finalMapInteractive
  delete message.finalClarification
}

function messageHasRevealWork(message) {
  clampMessageReveal(message)
  return (
    (message.streaming && message.revealedLength < message.content.length)
    || Boolean(message.doneReceived)
  )
}

function installRevealListeners(store) {
  revealStore = store
  if (revealListenersInstalled || typeof window === 'undefined') {
    return
  }

  revealListenersInstalled = true
  const motionQuery = getReducedMotionQuery()
  if (motionQuery) {
    const handleMotionChange = () => {
      if (motionQuery.matches) {
        revealStore?.snapStreamingMessages()
      } else {
        revealStore?.ensureRevealTicker()
      }
    }
    if (typeof motionQuery.addEventListener === 'function') {
      motionQuery.addEventListener('change', handleMotionChange)
    } else if (typeof motionQuery.addListener === 'function') {
      motionQuery.addListener(handleMotionChange)
    }
  }

  if (typeof document !== 'undefined' && typeof document.addEventListener === 'function') {
    documentWasHidden = document.visibilityState === 'hidden'
    document.addEventListener('visibilitychange', () => {
      if (document.visibilityState === 'hidden') {
        documentWasHidden = true
        return
      }
      if (documentWasHidden) {
        documentWasHidden = false
        revealStore?.snapStreamingMessages()
      }
    })
  }
}

function requestRevealFrame(store) {
  installRevealListeners(store)
  if (isRevealPacingDisabled()) {
    store.snapStreamingMessages()
    return
  }
  if (revealRafId !== null || !store.hasRevealWork()) {
    return
  }
  if (typeof window === 'undefined' || typeof window.requestAnimationFrame !== 'function') {
    return
  }
  revealLastTimestamp = null
  revealRafId = window.requestAnimationFrame(runRevealFrame)
}

function runRevealFrame(timestamp) {
  const store = revealStore
  revealRafId = null
  if (!store) {
    revealLastTimestamp = null
    return
  }
  if (isRevealPacingDisabled()) {
    store.snapStreamingMessages()
    revealLastTimestamp = null
    return
  }

  const previousTimestamp = revealLastTimestamp ?? timestamp
  const dtSeconds = Math.max(0, (timestamp - previousTimestamp) / 1000)
  revealLastTimestamp = timestamp

  if (store.advanceRevealFrame(dtSeconds)) {
    revealRafId = window.requestAnimationFrame(runRevealFrame)
  } else {
    revealLastTimestamp = null
  }
}

export const useChatStore = defineStore('chat', {
  state: () => ({
    messages: [],
    threadId: null,
    threads: [],
    isSending: false,
    error: '',
    lastFailedMessage: '',
    lastFailedRequest: null,
  }),
  getters: {
    isOriginSelectionPending: (state) => state.messages.some(
      (message) => message.map?.mode === 'ask_origin' && message.mapInteractive,
    ),
    isClarificationPending: (state) => state.messages.some(
      (message) => message.clarificationActive,
    ),
  },
  actions: {
    reset() {
      this.messages = []
      this.threadId = null
      this.threads = []
      this.isSending = false
      this.error = ''
      this.lastFailedMessage = ''
      this.lastFailedRequest = null
    },
    newChat() {
      this.messages = []
      this.threadId = null
      this.error = ''
      this.lastFailedMessage = ''
      this.lastFailedRequest = null
    },
    hasRevealWork() {
      return this.messages.some((message) => messageHasRevealWork(message))
    },
    advanceRevealFrame(dtSeconds) {
      for (const message of this.messages) {
        clampMessageReveal(message)
        if (message.streaming && message.revealedLength < message.content.length) {
          message.revealedLength = advanceRevealCount({
            revealed: message.revealedLength,
            total: message.content.length,
            dtSeconds,
          })
        }
        if (message.doneReceived && message.revealedLength >= message.content.length) {
          finalizeAssistantMessage(message)
        }
      }
      return this.hasRevealWork()
    },
    snapStreamingMessages() {
      for (const message of this.messages) {
        if (message.streaming || message.doneReceived) {
          message.revealedLength = message.content.length
        }
      }
      this.advanceRevealFrame(0)
    },
    ensureRevealTicker() {
      requestRevealFrame(this)
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
          map: message.map || null,
          mapInteractive: false,
          clarificationExpected: false,
          clarificationActive: false,
        }),
      )
      this.error = ''
      this.lastFailedMessage = ''
      this.lastFailedRequest = null
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
    async sendMessage(text, options = {}) {
      const messageText = text.trim()
      const originNode = options.originNode || null
      const originLabel = options.originLabel || ''
      const clarificationCardClientId = options.clarificationCardClientId || null
      if (
        !messageText
        || this.isSending
        || (this.isOriginSelectionPending && !originNode)
        || (this.isClarificationPending && !clarificationCardClientId)
      ) {
        return
      }

      this.deactivateMapCards()
      const userMessage = createMessage('user', messageText, originNode ? {
        map: {
          mode: 'origin_select',
          origin: { node: originNode, label: originLabel },
        },
      } : {})
      const assistantDraft = createMessage('assistant', '', {
        pending: true,
        statusText: '質問を分析しています…',
        statusStep: 'analyze',
      })
      this.messages.push(userMessage, assistantDraft)
      const assistantMessage = this.messages[this.messages.length - 1]
      this.isSending = true
      this.error = ''
      this.lastFailedMessage = ''
      this.lastFailedRequest = null

      try {
        await this.streamChatResponse(messageText, assistantMessage, { originNode })
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
        this.error = toFriendlyErrorMessage(error.message)
        assistantMessage.content = this.error
        assistantMessage.revealedLength = assistantMessage.content.length
        assistantMessage.sources = []
        assistantMessage.map = null
        assistantMessage.mapInteractive = false
        assistantMessage.clarificationExpected = false
        assistantMessage.clarificationActive = false
        delete assistantMessage.doneReceived
        delete assistantMessage.finalSources
        delete assistantMessage.finalMap
        delete assistantMessage.finalMapInteractive
        delete assistantMessage.finalClarification
        this.lastFailedMessage = messageText
        this.lastFailedRequest = {
          message: messageText,
          originNode,
          originLabel,
          originCardClientId: options.originCardClientId || null,
          clarificationCardClientId,
        }
        if (originNode && options.originCardClientId) {
          const originCard = this.messages.find(
            (message) => message.clientId === options.originCardClientId,
          )
          if (originCard?.map?.mode === 'ask_origin') {
            originCard.mapInteractive = true
          }
        }
        if (clarificationCardClientId) {
          const clarificationCard = this.messages.find(
            (message) => message.clientId === clarificationCardClientId,
          )
          if (clarificationCard) {
            clarificationCard.clarificationExpected = true
            clarificationCard.clarificationActive = true
          }
        }
      } finally {
        this.isSending = false
      }
    },
    deactivateMapCards() {
      for (const message of this.messages) {
        if (message.map?.mode === 'ask_origin') {
          message.mapInteractive = false
        }
        message.finalMapInteractive = false
        message.clarificationExpected = false
        message.clarificationActive = false
        message.finalClarification = false
      }
    },
    async selectMapOrigin(message, origin) {
      if (
        this.isSending
        || !message?.mapInteractive
        || message?.map?.mode !== 'ask_origin'
        || !origin?.node
        || !origin?.label
      ) {
        return
      }
      const question = String(message.map.question || '').trim()
      if (!question) {
        message.mapInteractive = false
        return
      }
      message.mapInteractive = false
      message.mapSelectedNode = origin.node
      message.mapCancelled = false
      await this.sendMessage(question, {
        originNode: origin.node,
        originLabel: origin.label,
        originCardClientId: message.clientId,
      })
    },
    async submitClarificationAnswer(message, text) {
      const answer = String(text || '').trim()
      if (
        this.isSending
        || !message?.clarificationActive
        || !answer
      ) {
        return
      }
      message.clarificationActive = false
      message.clarificationExpected = false
      message.clarificationDraft = answer
      await this.sendMessage(answer, {
        clarificationCardClientId: message.clientId,
      })
    },
    cancelClarification(message) {
      if (
        !message?.clarificationActive
        || this.isSending
      ) {
        return
      }
      message.clarificationActive = false
      message.clarificationExpected = false
      message.clarificationDraft = ''
      if (this.lastFailedRequest?.clarificationCardClientId === message.clientId) {
        this.error = ''
        this.lastFailedMessage = ''
        this.lastFailedRequest = null
      }
    },
    cancelMapOrigin(message) {
      if (
        !message?.mapInteractive
        || message?.map?.mode !== 'ask_origin'
        || this.isSending
      ) {
        return
      }
      message.mapInteractive = false
      message.mapSelectedNode = null
      message.mapCancelled = true
      if (this.lastFailedRequest?.originCardClientId === message.clientId) {
        this.error = ''
        this.lastFailedMessage = ''
        this.lastFailedRequest = null
      }
    },
    async retryLast() {
      const request = this.lastFailedRequest
      if (!request?.message || this.isSending) {
        return
      }
      // Replace the failed exchange (its user + assistant pair are always the
      // two most recent messages while the error banner is visible).
      if (this.messages.length >= 2) {
        this.messages.splice(this.messages.length - 2, 2)
      }
      this.error = ''
      this.lastFailedMessage = ''
      this.lastFailedRequest = null
      await this.sendMessage(request.message, {
        originNode: request.originNode,
        originLabel: request.originLabel,
        originCardClientId: request.originCardClientId,
        clarificationCardClientId: request.clarificationCardClientId,
      })
    },
    async streamChatResponse(text, assistantMessage, { originNode = null } = {}) {
      const token = getStoredToken()
      const requestBody = {
        message: text,
        thread_id: this.threadId,
      }
      if (originNode) {
        requestBody.origin_node = originNode
      }
      const response = await fetch('/api/chat', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          ...(token ? { Authorization: `Bearer ${token}` } : {}),
        },
        body: JSON.stringify(requestBody),
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
        this.ensureRevealTicker()
      }

      return incomplete
    },
  },
})

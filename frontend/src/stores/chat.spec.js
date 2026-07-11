import { watch } from 'vue'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'

import { applyAssistantEvent, createMessage, parseSseBlock, useChatStore } from './chat'

function createSseResponse(blocks) {
  const encoder = new TextEncoder()
  return {
    ok: true,
    status: 200,
    body: new ReadableStream({
      start(controller) {
        controller.enqueue(encoder.encode(`${blocks.join('\n\n')}\n\n`))
        controller.close()
      },
    }),
  }
}

describe('chat store SSE helpers', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
  })

  afterEach(() => {
    vi.restoreAllMocks()
    vi.unstubAllGlobals()
  })

  it('parses documented SSE event blocks', () => {
    const parsed = parseSseBlock('event: status\ndata: {"step":"analyze","text":"質問を分析しています…"}')
    expect(parsed).toEqual({
      event: 'status',
      data: {
        step: 'analyze',
        text: '質問を分析しています…',
      },
    })
  })

  it('switches from pending status to streamed tokens and done metadata', () => {
    const message = createMessage('assistant', '', {
      pending: true,
      statusText: '質問を分析しています…',
      statusStep: 'analyze',
      id: 'local-id',
    })

    applyAssistantEvent(message, {
      event: 'status',
      data: { step: 'retrieve', text: '学内ナレッジを検索しています…' },
    })
    expect(message.pending).toBe(true)
    expect(message.statusText).toBe('学内ナレッジを検索しています…')
    expect(message.statusStep).toBe('retrieve')

    applyAssistantEvent(message, {
      event: 'token',
      data: { text: '秋田県立大学' },
    })
    expect(message.pending).toBe(false)
    expect(message.streaming).toBe(true)
    expect(message.content).toBe('秋田県立大学')

    const threadId = applyAssistantEvent(message, {
      event: 'done',
      data: {
        thread_id: 'thread-1',
        message_id: 'message-1',
        sources: [{ title: '公式', url: 'https://example.test', type: 'web' }],
      },
    })
    expect(threadId).toBe('thread-1')
    expect(message.id).toBe('message-1')
    expect(message.streaming).toBe(false)
    expect(message.sources).toHaveLength(1)
    expect(message.clientId).toBe('local-id')
  })

  it('consumes complete SSE blocks and preserves incomplete buffers', () => {
    const store = useChatStore()
    const message = createMessage('assistant', '', { pending: true })
    const buffer = [
      'event: token',
      'data: {"text":"こんにちは"}',
      '',
      'event: token',
      'data: {"text":"、本荘',
    ].join('\n')

    const remaining = store.consumeSseBuffer(buffer, message)
    expect(message.content).toBe('こんにちは')
    expect(remaining).toBe('event: token\ndata: {"text":"、本荘')
  })

  it('streams into the reactive assistant message so Vue watchers observe token updates', async () => {
    const store = useChatStore()
    const contentSnapshots = []
    const streamedMessages = []
    const originalConsumeSseBuffer = store.consumeSseBuffer
    store.consumeSseBuffer = vi.fn((buffer, assistantMessage, flush = false) => {
      streamedMessages.push(assistantMessage)
      return originalConsumeSseBuffer.call(store, buffer, assistantMessage, flush)
    })

    const stop = watch(
      () => store.messages[1]?.content,
      (content) => contentSnapshots.push(content),
      { flush: 'sync' },
    )

    vi.stubGlobal('localStorage', {
      getItem: vi.fn(() => null),
      setItem: vi.fn(),
      removeItem: vi.fn(),
    })
    vi.stubGlobal(
      'fetch',
      vi.fn(() =>
        Promise.resolve(
          createSseResponse([
            'event: status\ndata: {"step":"retrieve","text":"学内ナレッジを検索しています…"}',
            'event: token\ndata: {"text":"本荘"}',
            'event: token\ndata: {"text":"キャンパス"}',
            'event: done\ndata: {"thread_id":"thread-1","message_id":"message-1","sources":[]}',
          ]),
        ),
      ),
    )

    await store.sendMessage('食堂はどこですか？')
    stop()

    expect(streamedMessages.length).toBeGreaterThan(0)
    expect(streamedMessages.every((message) => message === store.messages[1])).toBe(true)
    expect(contentSnapshots).toContain('本荘')
    expect(contentSnapshots).toContain('本荘キャンパス')
    expect(store.messages[1].content).toBe('本荘キャンパス')
    expect(store.messages[1].statusStep).toBe('retrieve')
  })
})

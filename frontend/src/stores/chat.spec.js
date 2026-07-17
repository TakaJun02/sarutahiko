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

function createJsonResponse(payload, status = 200) {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: () => Promise.resolve(payload),
  }
}

function stubLocalStorage() {
  vi.stubGlobal('localStorage', {
    getItem: vi.fn(() => 'test-token'),
    setItem: vi.fn(),
    removeItem: vi.fn(),
  })
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

  it('switches from pending status to streamed tokens and defers done metadata', () => {
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
    expect(message.revealedLength).toBe(0)

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
    expect(message.streaming).toBe(true)
    expect(message.sources).toHaveLength(0)
    expect(message.doneReceived).toBe(true)
    expect(message.finalSources).toHaveLength(1)
    expect(message.clientId).toBe('local-id')
  })

  it('defers sources and settled state until reveal reaches the full answer', () => {
    const store = useChatStore()
    const message = createMessage('assistant', '', { pending: true })
    store.messages = [message]

    applyAssistantEvent(message, {
      event: 'token',
      data: { text: '学生ホールにあります。' },
    })
    applyAssistantEvent(message, {
      event: 'done',
      data: {
        thread_id: 'thread-1',
        message_id: 'message-1',
        sources: [{ title: '公式', url: 'https://example.test', type: 'knowledge' }],
      },
    })

    expect(message.streaming).toBe(true)
    expect(message.sources).toEqual([])
    expect(message.doneReceived).toBe(true)

    message.revealedLength = message.content.length
    store.advanceRevealFrame(0.016)

    expect(message.streaming).toBe(false)
    expect(message.sources).toEqual([
      { title: '公式', url: 'https://example.test', type: 'knowledge' },
    ])
    expect(message.doneReceived).toBeUndefined()
    expect(message.finalSources).toBeUndefined()
  })

  it('defers map metadata until smooth reveal completes', () => {
    const store = useChatStore()
    const message = createMessage('assistant', '', { pending: true })
    store.messages = [message]
    const map = {
      mode: 'ask_origin',
      prompt: 'いまいる場所をマップでタップしてください',
      question: 'D414 に行きたい',
    }

    applyAssistantEvent(message, { event: 'token', data: { text: '場所を教えてください' } })
    applyAssistantEvent(message, { event: 'map', data: map })
    applyAssistantEvent(message, {
      event: 'done',
      data: { thread_id: 'thread-1', message_id: 'message-1', sources: [] },
    })

    expect(message.map).toBeNull()
    expect(message.mapInteractive).toBe(false)
    expect(message.finalMap).toEqual(map)

    message.revealedLength = message.content.length
    store.advanceRevealFrame(0.016)

    expect(message.map).toEqual(map)
    expect(message.mapInteractive).toBe(true)
    expect(message.finalMap).toBeUndefined()
  })

  it('sends the specified synthetic message and deactivates the ask-origin card', async () => {
    const store = useChatStore()
    const message = createMessage('assistant', '現在地を選んでください', {
      map: { mode: 'ask_origin', question: 'D414 に行きたい' },
      mapInteractive: true,
    })
    store.messages = [message]
    store.sendMessage = vi.fn(() => Promise.resolve())

    await store.selectMapOrigin(message, {
      node: 'cafeteria',
      label: 'カフェテリア（食堂）',
    })

    expect(message.mapInteractive).toBe(false)
    expect(store.sendMessage).toHaveBeenCalledWith(
      '現在地はカフェテリア（食堂）です。D414 に行きたい',
    )
  })

  it('prevents a pending ask-origin card from reactivating after another send', () => {
    const store = useChatStore()
    const previous = createMessage('assistant', '前の現在地確認', {
      map: { mode: 'ask_origin', question: 'D404 に行きたい' },
      mapInteractive: true,
    })
    const latest = createMessage('assistant', '新しい現在地確認', {
      streaming: true,
      revealedLength: 0,
      doneReceived: true,
      finalSources: [],
      finalMap: { mode: 'ask_origin', question: 'D414 に行きたい' },
      finalMapInteractive: true,
    })
    store.messages = [previous, latest]

    store.deactivateMapCards()
    store.snapStreamingMessages()

    expect(previous.mapInteractive).toBe(false)
    expect(latest.revealedLength).toBe(latest.content.length)
    expect(latest.map).toEqual({ mode: 'ask_origin', question: 'D414 に行きたい' })
    expect(latest.mapInteractive).toBe(false)
  })

  it('snaps revealed length on assistant error events', () => {
    const message = createMessage('assistant', '', { pending: true })

    applyAssistantEvent(message, {
      event: 'token',
      data: { text: '途中まで' },
    })
    applyAssistantEvent(message, {
      event: 'error',
      data: { message: '回答生成中にエラーが発生しました。' },
    })

    expect(message.streaming).toBe(false)
    expect(message.content).toBe('回答生成中にエラーが発生しました。')
    expect(message.revealedLength).toBe(message.content.length)
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

describe('chat store thread history actions', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    stubLocalStorage()
  })

  afterEach(() => {
    vi.restoreAllMocks()
    vi.unstubAllGlobals()
  })

  it('loads the thread list from the API', async () => {
    const threads = [
      { id: 'thread-2', title: '図書館について', created_at: 'c2', updated_at: 'u2' },
      { id: 'thread-1', title: '食堂について', created_at: 'c1', updated_at: 'u1' },
    ]
    vi.stubGlobal('fetch', vi.fn(() => Promise.resolve(createJsonResponse({ threads }))))

    const store = useChatStore()
    await store.loadThreads()

    expect(fetch).toHaveBeenCalledWith('/api/threads', expect.any(Object))
    expect(store.threads).toEqual(threads)
  })

  it('restores a persisted thread with settled assistant messages and sources', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(() =>
        Promise.resolve(
          createJsonResponse({
            thread: { id: 'thread-1', title: '食堂について', created_at: 'c1', updated_at: 'u1' },
            messages: [
              { id: 'm1', role: 'user', content: '食堂はどこですか？', sources: [], created_at: 't1' },
              {
                id: 'm2',
                role: 'assistant',
                content: '学生ホールにあります。',
                sources: [{ title: '公式', url: 'https://example.test', type: 'knowledge' }],
                map: {
                  mode: 'place',
                  destination: { node: 'g1', label: '学部棟Ⅰ', room: 'GI512', floor: 5 },
                },
                created_at: 't2',
              },
            ],
          }),
        ),
      ),
    )

    const store = useChatStore()
    await store.openThread('thread-1')

    expect(store.threadId).toBe('thread-1')
    expect(store.messages).toHaveLength(2)
    expect(store.messages[0].role).toBe('user')
    expect(store.messages[0].content).toBe('食堂はどこですか？')
    expect(store.messages[1]).toMatchObject({
      id: 'm2',
      role: 'assistant',
      content: '学生ホールにあります。',
      revealedLength: '学生ホールにあります。'.length,
      pending: false,
      streaming: false,
    })
    expect(store.messages[1].sources).toEqual([
      { title: '公式', url: 'https://example.test', type: 'knowledge' },
    ])
    expect(store.messages[1].map.mode).toBe('place')
    expect(store.messages[1].mapInteractive).toBe(false)
    expect(store.messages.every((message) => message.revealedLength === message.content.length)).toBe(true)
  })

  it('restores an ask-origin card as inactive after history reload', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(() =>
        Promise.resolve(
          createJsonResponse({
            thread: { id: 'thread-ask', title: 'D414', created_at: 'c1', updated_at: 'u1' },
            messages: [
              {
                id: 'm-ask',
                role: 'assistant',
                content: 'いまいる場所を教えてください。',
                sources: [],
                map: {
                  mode: 'ask_origin',
                  question: 'D414 に行きたい',
                  destination: { node: 'd', label: '大学院棟', room: 'D414', floor: 4 },
                },
                created_at: 't1',
              },
            ],
          }),
        ),
      ),
    )

    const store = useChatStore()
    await store.openThread('thread-ask')

    expect(store.messages[0].map.mode).toBe('ask_origin')
    expect(store.messages[0].mapInteractive).toBe(false)
  })

  it('starts a new chat without dropping the sidebar list', () => {
    const store = useChatStore()
    store.threads = [{ id: 'thread-1', title: 't', created_at: 'c', updated_at: 'u' }]
    store.threadId = 'thread-1'
    store.messages = [createMessage('user', 'こんにちは')]
    store.error = '一時的なエラー'

    store.newChat()

    expect(store.messages).toEqual([])
    expect(store.threadId).toBeNull()
    expect(store.error).toBe('')
    expect(store.threads).toHaveLength(1)
  })

  it('renames a thread and updates the sidebar entry', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(() =>
        Promise.resolve(
          createJsonResponse({
            thread: { id: 'thread-1', title: '学食まとめ', created_at: 'c1', updated_at: 'u1' },
          }),
        ),
      ),
    )

    const store = useChatStore()
    store.threads = [
      { id: 'thread-1', title: '食堂について', created_at: 'c1', updated_at: 'u1' },
      { id: 'thread-2', title: '図書館について', created_at: 'c2', updated_at: 'u2' },
    ]

    await store.renameThread('thread-1', '学食まとめ')

    const [url, options] = fetch.mock.calls[0]
    expect(url).toBe('/api/threads/thread-1')
    expect(options.method).toBe('PATCH')
    expect(JSON.parse(options.body)).toEqual({ title: '学食まとめ' })
    expect(store.threads[0].title).toBe('学食まとめ')
    expect(store.threads[1].title).toBe('図書館について')
  })

  it('deletes a thread and resets the conversation when it was open', async () => {
    vi.stubGlobal('fetch', vi.fn(() => Promise.resolve(createJsonResponse(null, 204))))

    const store = useChatStore()
    store.threads = [
      { id: 'thread-1', title: '食堂について', created_at: 'c1', updated_at: 'u1' },
      { id: 'thread-2', title: '図書館について', created_at: 'c2', updated_at: 'u2' },
    ]
    store.threadId = 'thread-1'
    store.messages = [createMessage('user', '食堂はどこですか？')]

    await store.deleteThread('thread-1')

    const [url, options] = fetch.mock.calls[0]
    expect(url).toBe('/api/threads/thread-1')
    expect(options.method).toBe('DELETE')
    expect(store.threads.map((thread) => thread.id)).toEqual(['thread-2'])
    expect(store.threadId).toBeNull()
    expect(store.messages).toEqual([])
  })

  it('keeps the current conversation when deleting another thread', async () => {
    vi.stubGlobal('fetch', vi.fn(() => Promise.resolve(createJsonResponse(null, 204))))

    const store = useChatStore()
    store.threads = [
      { id: 'thread-1', title: '食堂について', created_at: 'c1', updated_at: 'u1' },
      { id: 'thread-2', title: '図書館について', created_at: 'c2', updated_at: 'u2' },
    ]
    store.threadId = 'thread-2'
    store.messages = [createMessage('user', '図書館は使えますか？')]

    await store.deleteThread('thread-1')

    expect(store.threads.map((thread) => thread.id)).toEqual(['thread-2'])
    expect(store.threadId).toBe('thread-2')
    expect(store.messages).toHaveLength(1)
  })

  it('refreshes the thread list after a send resolves a thread id', async () => {
    const threads = [{ id: 'thread-1', title: '食堂はどこですか？', created_at: 'c1', updated_at: 'u1' }]
    vi.stubGlobal(
      'fetch',
      vi.fn((url) => {
        if (url === '/api/chat') {
          return Promise.resolve(
            createSseResponse([
              'event: token\ndata: {"text":"学生ホールです。"}',
              'event: done\ndata: {"thread_id":"thread-1","message_id":"message-1","sources":[]}',
            ]),
          )
        }
        return Promise.resolve(createJsonResponse({ threads }))
      }),
    )

    const store = useChatStore()
    await store.sendMessage('食堂はどこですか？')

    expect(store.threadId).toBe('thread-1')
    expect(fetch).toHaveBeenCalledWith('/api/threads', expect.any(Object))
    expect(store.threads).toEqual(threads)
  })
})

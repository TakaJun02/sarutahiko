import { readFileSync } from 'node:fs'

import { describe, expect, it } from 'vitest'

const chatViewSource = readFileSync(new URL('./ChatView.vue', import.meta.url), 'utf8')
const normalizedSource = chatViewSource.replace(/\s+/g, ' ')

describe('ChatView about dialog', () => {
  it('keeps the FR-22 copy in the required order before the laboratory link', () => {
    const orderedContent = [
      'APU-Navi は、秋田県立大学 サイバーフィジカルシステム研究室【CPS Lab】によって開発されました！',
      'お手元のスマートフォンでも使えます',
      'この QR コードを読み取ると、APU-Navi（このアプリ本体）が開きます。',
      'ibera.cps.akita-pu.ac.jp',
      'サイバーフィジカルシステム研究室のHPはこちらをクリック！',
    ]

    const positions = orderedContent.map((content) => normalizedSource.indexOf(content))
    expect(positions.every((position) => position >= 0)).toBe(true)
    expect(positions).toEqual([...positions].sort((left, right) => left - right))
  })

  it('renders an unmodified 160px QR image with meaningful alternative text', () => {
    const qrImage = chatViewSource.match(
      /<img\s+src="\/qrcode_ibera\.cps\.akita-pu\.ac\.jp\.png"[\s\S]*?\/>/,
    )?.[0]

    expect(qrImage).toBeDefined()
    expect(qrImage).toContain('alt="APU-Navi アクセス用 QR コード"')
    expect(qrImage).toContain('h-40 w-40')
    expect(qrImage).not.toMatch(/opacity|filter|mix-blend|invert/)
  })

  it('guards every dialog panel against viewport overflow', () => {
    expect(chatViewSource).toContain('class="absolute inset-0 z-50 flex')
    expect(chatViewSource).not.toContain('class="fixed inset-0 z-50 flex')
    expect(chatViewSource).toContain('pt-[calc(1rem_+_env(safe-area-inset-top))]')
    expect(chatViewSource).toContain('max-h-full')
    expect(chatViewSource).toContain('overflow-y-auto overscroll-contain')
  })

  it('prevents initial dialog focus from scrolling the panel', () => {
    expect(chatViewSource).toContain('element?.focus({ preventScroll: true })')
    expect(chatViewSource).toContain('focusDialogElement(dialogInputRef.value)')
    expect(chatViewSource).toContain('dialogInputRef.value?.select()')
    expect(chatViewSource).toContain('focusDialogElement(dialogCancelRef.value)')
  })
})

describe('ChatView FR-24 scrolling', () => {
  it('renders the latest-message button with focus-preserving glass styling', () => {
    const button = chatViewSource.match(
      /<button\s+v-if="chat\.messages\.length > 0 && !isAtBottom"[\s\S]*?aria-label="最新のメッセージへ移動"[\s\S]*?<\/button>/,
    )?.[0]

    expect(button).toBeDefined()
    expect(button).toContain('@mousedown.prevent')
    expect(button).toContain('h-11 w-11')
    expect(button).toContain('rounded-full')
    expect(button).toContain('border-edge-strong')
    expect(button).toContain('bg-ink-raised/70')
    expect(button).toContain('shadow-glass')
    expect(button).toContain('backdrop-blur-md')
  })

  it('gates message-signature auto-following on the bottom state', () => {
    expect(normalizedSource).toContain(
      "if (pendingScrollBehavior || isAtBottom.value) { scrollToBottom('auto') }",
    )
  })

  it('includes revealed length in the message-signature auto-follow trigger', () => {
    expect(normalizedSource).toContain('message.content.length}:${message.revealedLength}')
  })

  it('measures the visual bottom after subtracting the sticky footer height', () => {
    expect(normalizedSource).toContain(
      'const effectiveGap = scrollContainer.scrollHeight - currentScrollTop - scrollContainer.clientHeight - (footerRef.value?.offsetHeight || 0)',
    )
    expect(normalizedSource).toContain(
      'if (effectiveGap <= AT_BOTTOM_THRESHOLD_PX) { isAtBottom.value = true',
    )
  })

  it('only leaves the bottom state during an upward scroll beyond the threshold', () => {
    expect(normalizedSource).toContain(
      'effectiveGap > AT_BOTTOM_THRESHOLD_PX && currentScrollTop < lastScrollTop',
    )
    expect(normalizedSource).toContain('isAtBottom.value = false')
    expect(normalizedSource).toContain('lastScrollTop = currentScrollTop')
  })

  it('does not use a time-based smooth-scroll suppression window', () => {
    expect(chatViewSource).not.toContain('SMOOTH_SCROLL_SUPPRESS_MS')
    expect(chatViewSource).not.toContain('smoothScrollSuppressUntil')
  })

  it('requests smooth scrolling when send starts', () => {
    const sendSource = chatViewSource.match(
      /async function send\(\) \{[\s\S]*?\n\}\n\nfunction onEnter/,
    )?.[0]

    expect(sendSource).toContain("pendingScrollBehavior = 'smooth'")
  })
})

describe('ChatView FR-25 smooth reveal', () => {
  it('passes only the revealed slice to MarkdownRenderer', () => {
    expect(normalizedSource).toContain(
      'function revealedMessageContent(message) { return message.content.slice(0, message.revealedLength ?? message.content.length) }',
    )
    expect(normalizedSource).toContain(':content="revealedMessageContent(message)"')
  })

  it('renders map metadata in the settled body before sources', () => {
    expect(chatViewSource).toContain("import MapCard from '../components/MapCard.vue'")
    const mapPosition = normalizedSource.indexOf('<MapCard v-if="message.map"')
    const sourcesPosition = normalizedSource.indexOf('<div v-if="message.sources.length"')
    expect(mapPosition).toBeGreaterThan(0)
    expect(sourcesPosition).toBeGreaterThan(mapPosition)
    expect(normalizedSource).toContain(':interactive="message.mapInteractive"')
    expect(normalizedSource).toContain(':selected-node-id="message.mapSelectedNode || \'\'"')
    expect(normalizedSource).toContain('@origin-selected="selectMapOrigin(message, $event)"')
  })
})

describe('ChatView FR-27 origin selection flow', () => {
  it('locks every composer entry point and switches the placeholder', () => {
    expect(normalizedSource).toContain(
      "chat.isOriginSelectionPending ? 'マップから現在地を選んでください' : '質問を入力'",
    )
    expect(normalizedSource).toContain(':disabled="chat.isOriginSelectionPending" @keydown.enter="onEnter"')
    expect(normalizedSource).toContain(
      ':disabled="!draft.trim() || chat.isSending || chat.isOriginSelectionPending"',
    )
    expect(normalizedSource).toContain(
      ':disabled="chat.isOriginSelectionPending || chat.isSending"',
    )
    expect(normalizedSource).toContain(
      'event.preventDefault() if (chat.isOriginSelectionPending) { return }',
    )
  })

  it('wires the explicit card cancellation escape hatch', () => {
    expect(normalizedSource).toContain('@origin-cancelled="cancelMapOrigin(message)"')
    expect(normalizedSource).toContain('chat.cancelMapOrigin(message)')
  })

  it('renders origin-select user turns as a location chip instead of message content', () => {
    const chipPosition = normalizedSource.indexOf('v-if="message.map?.mode === \'origin_select\'"')
    const normalBubblePosition = normalizedSource.indexOf('<p v-else class="max-w-[88%]')
    expect(chipPosition).toBeGreaterThan(0)
    expect(normalBubblePosition).toBeGreaterThan(chipPosition)
    expect(normalizedSource).toContain('class="current-location-chip"')
    expect(normalizedSource).toContain('<small>現在地:</small>')
    expect(normalizedSource).toContain('{{ message.map.origin?.label }}')
  })
})

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

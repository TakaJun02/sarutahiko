import { readFileSync } from 'node:fs'

import { describe, expect, it } from 'vitest'

const source = readFileSync(new URL('./MapCard.vue', import.meta.url), 'utf8')
const graphicSource = readFileSync(new URL('./CampusMapGraphic.vue', import.meta.url), 'utf8')
const normalized = source.replace(/\s+/g, ' ')
const normalizedGraphic = graphicSource.replace(/\s+/g, ' ')
const mapImage = readFileSync(new URL('../assets/honjo-campus-map.png', import.meta.url))

describe('MapCard FR-30 vector map contract', () => {
  it('draws the campus as inline vector geometry instead of using the PNG as card background', () => {
    expect(normalized).toContain("import CampusMapGraphic from './CampusMapGraphic.vue'")
    expect(normalized).toContain(':view-box="cardViewBox"')
    expect(normalized).toContain('fitMapViewBox(props.payload, canvasAspect.value)')
    expect(normalizedGraphic).toContain('class="campus-map-buildings"')
    expect(normalizedGraphic).toContain('class="campus-map-building campus-map-building--common"')
    expect(normalizedGraphic).toContain('class="campus-map-building campus-map-building--round"')
    expect(normalizedGraphic).toContain('class="campus-map-roads"')
    expect(normalizedGraphic).toContain('class="campus-map-rotary')
    expect(normalizedGraphic).toContain('class="campus-map-parking"')
    expect(normalizedGraphic).not.toContain('<image')
  })

  it('keeps the approved 671x720 PNG only for the official-map viewer switch', () => {
    expect(mapImage.subarray(1, 4).toString()).toBe('PNG')
    expect(mapImage.readUInt32BE(16)).toBe(671)
    expect(mapImage.readUInt32BE(20)).toBe(720)
    expect(normalized).toContain("import campusMapImage from '../assets/honjo-campus-map.png'")
    expect(normalized).toContain('公式マップを見る')
    expect(normalized).toContain(':src="campusMapImage"')
    expect(normalized).not.toContain('<image class="map-card__image"')
  })

  it('traces all eight named footprints and keeps labels readable at 375px', () => {
    const labels = [
      '大学院棟', '特別実験棟', '学部棟Ⅰ', '学部棟Ⅱ',
      '体育館', 'メディア', '共通施設棟', '南側多目的広場',
    ]
    labels.forEach((label) => expect(normalizedGraphic).toContain(label))
    expect(graphicSource).toMatch(/\.campus-map-landmark-labels text\s*\{[\s\S]*?font-size:\s*18px/)
    expect(graphicSource).toMatch(/\.campus-map-floor-badge text,[\s\S]*?font-size:\s*15px/)
  })

  it('keeps route geometry schematic and shows the required disclaimer', () => {
    expect(normalizedGraphic).toContain(':d="edgePath(edge)"')
    expect(normalized).toContain('※経路線は建物間のつながりを模式的に示したものです（実際の通路とは異なる場合があります）')
    expect(normalizedGraphic).not.toContain('歩行通路')
  })

  it('uses a full-bleed map at least 1.3 times the previous mobile height', () => {
    expect(source).toMatch(/\.map-card__canvas\s*\{[\s\S]*?width:\s*100%/)
    expect(source).toMatch(/\.map-card__canvas\s*\{[\s\S]*?min-height:\s*348px/)
    expect(source).not.toMatch(/\.map-card__canvas\s*\{[\s\S]*?margin:/)
  })
})

describe('MapCard full-screen viewer contract', () => {
  it('teleports an absolute safe-area and overscroll-contained dialog into the chat shell', () => {
    expect(normalized).toContain('<Teleport to=".chat-shell">')
    expect(normalized).toContain('role="dialog" aria-modal="true"')
    expect(source).toMatch(/\.map-viewer\s*\{[\s\S]*?position:\s*absolute/)
    expect(source).not.toMatch(/\.map-viewer\s*\{[\s\S]*?position:\s*fixed/)
    expect(source).toMatch(/\.map-viewer\s*\{[\s\S]*?overscroll-behavior:\s*contain/)
    expect(source).toContain('padding-top: env(safe-area-inset-top)')
    expect(source).toContain('padding-bottom: env(safe-area-inset-bottom)')
  })

  it('implements pinch, double-tap, wheel zoom, and pan with CSS transforms', () => {
    expect(normalized).toContain('@pointerdown="onViewerPointerDown"')
    expect(normalized).toContain('@pointermove="onViewerPointerMove"')
    expect(normalized).toContain("gesture.type === 'pinch'")
    expect(normalized).toContain("gesture.type === 'pan'")
    expect(normalized).toContain('isMapDoubleTap(lastTap, tap)')
    expect(normalized).toContain('@wheel.prevent="onViewerWheel"')
    expect(normalized).toContain('transform: `translate3d(${viewerX.value}px, ${viewerY.value}px, 0) scale(${viewerScale.value})`')
    expect(source).toMatch(/\.map-viewer__viewport\s*\{[\s\S]*?touch-action:\s*none/)
  })

  it('supports ask-origin selection from both the full-screen SVG and 44px chips', () => {
    expect(normalized).toContain(':interactive="active"')
    expect(normalized).toContain('@origin-selected="selectNode"')
    expect(normalized).toContain('aria-label="全画面マップで現在地を選択"')
    expect(source).toMatch(/\.map-viewer__origin-chips button\s*\{[\s\S]*?min-height:\s*44px/)
    expect(normalized).toContain("emit('origin-selected', { node: node.node, label: node.label })")
  })

  it('traps focus, restores it, closes on Escape, and applies reduced-motion immediately', () => {
    expect(normalized).toContain("if (event.key === 'Escape')")
    expect(normalized).toContain('viewerCloseRef.value?.focus({ preventScroll: true })')
    expect(normalized).toContain('focusTarget?.focus({ preventScroll: true })')
    expect(normalized).toContain("event.key !== 'Tab'")
    expect(source).toContain('@media (prefers-reduced-motion: reduce)')
    expect(source).toMatch(/@media \(prefers-reduced-motion: reduce\)[\s\S]*?transition:\s*none !important/)
    expect(normalized).toContain("window.matchMedia('(prefers-reduced-motion: reduce)')")
  })
})

describe('MapCard preserved FR-27 states and information', () => {
  it('keeps equivalent SVG and chip controls with accessible names and 44px targets', () => {
    expect(normalizedGraphic).toContain(':role="isAskOrigin ? \'button\' : undefined"')
    expect(normalizedGraphic).toContain('@keydown="onNodeKeydown($event, node)"')
    expect(normalized).toContain('aria-label="現在地をノード名から選択"')
    expect(source).toMatch(/\.map-card__chip\s*\{[\s\S]*?min-height:\s*44px/)
    expect(normalizedGraphic).toContain('<circle class="campus-map-node__target" cy="-12" r="45"')
  })

  it('retains selected, cancelled, history, destination, badge, and step states', () => {
    expect(normalized).toContain("if (active.value) return '選択受付中'")
    expect(normalized).toContain("if (props.selectedNodeId) return '選択済み'")
    expect(normalized).toContain("if (props.cancelled) return '受付終了'")
    expect(normalized).toContain("return '履歴'")
    expect(normalized).toContain('destinationLabel')
    expect(normalizedGraphic).toContain('groundNotes')
    expect(normalizedGraphic).toContain('edgeBadgeText(edge)')
    expect(normalized).toContain('<details v-if="isRoute && payload.steps?.length"')
    expect(normalized).toContain('現在地を選ばずに続ける')
  })

  it('removes the old artificial eyebrow and equal-size selection grid treatment', () => {
    expect(source).not.toContain('map-card__eyebrow')
    expect(source).not.toContain('HONJO CAMPUS')
    expect(source).not.toContain('STEP BY STEP')
    expect(source).toMatch(/\.map-card__chips\s*\{[\s\S]*?display:\s*flex[\s\S]*?flex-wrap:\s*wrap/)
  })
})

import { readFileSync } from 'node:fs'

import { describe, expect, it } from 'vitest'

const source = readFileSync(new URL('./MapCard.vue', import.meta.url), 'utf8')
const normalized = source.replace(/\s+/g, ' ')

describe('MapCard FR-26 contract', () => {
  it('offers equivalent SVG and chip controls with accessible names', () => {
    expect(normalized).toContain(':role="isAskOrigin ? \'button\' : undefined"')
    expect(normalized).toContain(':tabindex="active ? 0 : undefined"')
    expect(normalized).toContain('@keydown="onNodeKeydown($event, node)"')
    expect(normalized).toContain('aria-label="現在地をノード名から選択"')
    expect(normalized).toContain(':aria-label="`現在地を${node.selectionLabel}にする`"')
  })

  it('keeps all chip tap targets at least 44px high', () => {
    expect(source).toMatch(/\.map-card__chip\s*\{[\s\S]*?min-height:\s*44px/)
    expect(source).toMatch(/\.map-card__steps summary\s*\{[\s\S]*?min-height:\s*44px/)
    expect(source).toMatch(/\.map-card__cancel\s*\{[\s\S]*?min-height:\s*44px/)
    expect(normalized).toContain('class="map-node__target" x="-37" y="-29" width="74" height="58"')
  })

  it('has reduced-motion overrides and no horizontal scrolling', () => {
    expect(source).toContain('@media (prefers-reduced-motion: reduce)')
    expect(source).toContain('animation: none !important')
    expect(source).toMatch(/\.map-card\s*\{[\s\S]*?max-width:\s*100%[\s\S]*?overflow:\s*hidden/)
    expect(source).not.toContain('overflow-x: auto')
  })

  it('renders destination, floor, minute, and step information', () => {
    expect(normalized).toContain('destinationLabel')
    expect(normalized).toContain('groundNotes')
    expect(normalized).toContain('edgeBadge(edge)')
    expect(normalized).toContain('<details v-if="isRoute && payload.steps?.length"')
  })

  it('distinguishes active, selected, cancelled, and history ask-origin states', () => {
    expect(normalized).toContain("if (active.value) return '選択受付中'")
    expect(normalized).toContain("if (props.selectedNodeId) return '選択済み'")
    expect(normalized).toContain("if (props.cancelled) return '受付終了'")
    expect(normalized).toContain("return '履歴'")
    expect(normalized).toContain("defineEmits(['origin-selected', 'origin-cancelled'])")
    expect(normalized).toContain('現在地を選ばずに続ける')
    expect(normalized).toContain(':aria-pressed="selectedNodeId === node.id"')
  })

  it('uses Campus Signal tokens and disables every decorative map animation for reduced motion', () => {
    expect(source).toContain('--map-signal: #ff7657')
    expect(source).toContain('font-family: "Space Grotesk"')
    expect(source).toContain('background: rgba(8, 10, 9, 0.16)')
    expect(source).toMatch(/@media \(prefers-reduced-motion: reduce\)[\s\S]*?\.map-edge--active[\s\S]*?animation: none !important/)
  })

  it('renders curated sign codes instead of raw internal ids', () => {
    expect(normalized).toContain('{{ node.displayCode }}')
    expect(normalized).not.toContain('node.id.toUpperCase()')
  })

  it('shows the schematic disclaimer in every mode', () => {
    expect(normalized).toContain('<p class="map-card__schematic-note">')
    expect(normalized).toContain('※模式図（縮尺・方位は実際と異なります）')
    expect(source).toMatch(/\.map-card__schematic-note\s*\{[\s\S]*?font-size:\s*0\.625rem/)
  })
})

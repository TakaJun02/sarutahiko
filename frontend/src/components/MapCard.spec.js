import { readFileSync } from 'node:fs'

import { describe, expect, it } from 'vitest'

const source = readFileSync(new URL('./MapCard.vue', import.meta.url), 'utf8')
const normalized = source.replace(/\s+/g, ' ')
const mapImage = readFileSync(new URL('../assets/honjo-campus-map.png', import.meta.url))

describe('MapCard real campus map contract', () => {
  it('bundles the approved 671x720 map and renders it in the cropped SVG', () => {
    expect(mapImage.subarray(1, 4).toString()).toBe('PNG')
    expect(mapImage.readUInt32BE(16)).toBe(671)
    expect(mapImage.readUInt32BE(20)).toBe(720)
    expect(normalized).toContain("import campusMapImage from '../assets/honjo-campus-map.png'")
    expect(normalized).toContain(':viewBox="CAMPUS_MAP_VIEWBOX"')
    expect(normalized).toContain('<image class="map-card__image" :href="campusMapImage"')
    expect(normalized).not.toContain('map-card__grid')
  })

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
    expect(normalized).toContain('<circle class="map-node__target" cy="-12" r="45"')
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

  it('shows the real-map route disclaimer in every mode', () => {
    expect(normalized).toContain('<p class="map-card__schematic-note">')
    expect(normalized).toContain('※経路線は建物間のつながりを模式的に示したものです（実際の通路とは異なる場合があります）')
    expect(source).toMatch(/\.map-card__schematic-note\s*\{[\s\S]*?font-size:\s*0\.625rem/)
  })
})

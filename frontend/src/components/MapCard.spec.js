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
    expect(normalized).toContain('<details v-if="payload.mode === \'route\' && payload.steps?.length"')
  })

  it('shows the schematic disclaimer in every mode', () => {
    expect(normalized).toContain(
      '<p class="map-card__schematic-note">※模式図（縮尺・方位は実際と異なります）</p>',
    )
    expect(source).toMatch(/\.map-card__schematic-note\s*\{[\s\S]*?font-size:\s*0\.625rem/)
  })
})

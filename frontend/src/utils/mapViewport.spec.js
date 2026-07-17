import { describe, expect, it } from 'vitest'

import {
  clampMapScale,
  constrainMapTransform,
  isMapDoubleTap,
  pinchMapAt,
  zoomMapAt,
} from './mapViewport'

describe('full-screen map viewport transforms', () => {
  it('clamps scale to 1x through 4x and removes pan at the reset scale', () => {
    expect(clampMapScale(0.4)).toBe(1)
    expect(clampMapScale(8)).toBe(4)
    expect(constrainMapTransform({ scale: 1, x: 200, y: -200, width: 375, height: 600 }))
      .toEqual({ scale: 1, x: 0, y: 0 })
  })

  it('keeps pan within the transformed map bounds', () => {
    expect(constrainMapTransform({ scale: 2, x: 999, y: -999, width: 360, height: 600 }))
      .toEqual({ scale: 2, x: 180, y: -300 })
  })

  it('zooms around the tapped point instead of jumping to the center', () => {
    expect(zoomMapAt({
      scale: 1,
      x: 0,
      y: 0,
      targetScale: 2.5,
      anchorX: 80,
      anchorY: -120,
      width: 360,
      height: 600,
    })).toEqual({ scale: 2.5, x: -120, y: 180 })
  })

  it('combines pinch scaling with movement of the gesture center', () => {
    expect(pinchMapAt({
      startScale: 1,
      startX: 0,
      startY: 0,
      startCenter: { x: 180, y: 300 },
      currentCenter: { x: 200, y: 330 },
      distanceRatio: 2,
      viewportCenter: { x: 180, y: 300 },
      width: 360,
      height: 600,
    })).toEqual({ scale: 2, x: 20, y: 30 })
  })

  it('recognises only nearby taps inside the double-tap window', () => {
    const first = { time: 1000, x: 100, y: 120 }
    expect(isMapDoubleTap(first, { time: 1250, x: 112, y: 127 })).toBe(true)
    expect(isMapDoubleTap(first, { time: 1400, x: 112, y: 127 })).toBe(false)
    expect(isMapDoubleTap(first, { time: 1250, x: 160, y: 180 })).toBe(false)
  })
})

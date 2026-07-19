export const MAP_VIEWER_SCALE = Object.freeze({ minimum: 1, maximum: 4 })

export function clampMapScale(scale) {
  return Math.min(
    MAP_VIEWER_SCALE.maximum,
    Math.max(MAP_VIEWER_SCALE.minimum, scale),
  )
}

export function constrainMapTransform({ scale, x, y, width, height }) {
  const nextScale = clampMapScale(scale)
  const maximumX = Math.max(0, width * (nextScale - 1) / 2)
  const maximumY = Math.max(0, height * (nextScale - 1) / 2)

  return {
    scale: nextScale,
    x: maximumX === 0 ? 0 : Math.min(maximumX, Math.max(-maximumX, x)),
    y: maximumY === 0 ? 0 : Math.min(maximumY, Math.max(-maximumY, y)),
  }
}

export function zoomMapAt({
  scale,
  x,
  y,
  targetScale,
  anchorX,
  anchorY,
  width,
  height,
}) {
  const nextScale = clampMapScale(targetScale)
  const ratio = nextScale / scale
  return constrainMapTransform({
    scale: nextScale,
    x: anchorX - ratio * (anchorX - x),
    y: anchorY - ratio * (anchorY - y),
    width,
    height,
  })
}

export function pinchMapAt({
  startScale,
  startX,
  startY,
  startCenter,
  currentCenter,
  distanceRatio,
  viewportCenter,
  width,
  height,
}) {
  const nextScale = clampMapScale(startScale * distanceRatio)
  const ratio = nextScale / startScale
  return constrainMapTransform({
    scale: nextScale,
    x: (currentCenter.x - viewportCenter.x)
      - ratio * (startCenter.x - viewportCenter.x - startX),
    y: (currentCenter.y - viewportCenter.y)
      - ratio * (startCenter.y - viewportCenter.y - startY),
    width,
    height,
  })
}

export function isMapDoubleTap(previousTap, currentTap, maximumDelay = 320, maximumDistance = 32) {
  return Boolean(
    previousTap
    && currentTap.time - previousTap.time < maximumDelay
    && Math.hypot(currentTap.x - previousTap.x, currentTap.y - previousTap.y) < maximumDistance
  )
}

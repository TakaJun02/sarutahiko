export const MIN_REVEAL_RATE = 40
export const DRAIN_SECONDS = 0.9
const MAX_FRAME_DT_SECONDS = 0.1

export function advanceRevealCount({ revealed, total, dtSeconds }) {
  const backlog = Math.max(0, total - revealed)
  if (backlog === 0) {
    return revealed
  }

  const clampedDt = Math.min(
    MAX_FRAME_DT_SECONDS,
    Math.max(0, Number.isFinite(dtSeconds) ? dtSeconds : 0),
  )
  const rate = Math.max(MIN_REVEAL_RATE, backlog / DRAIN_SECONDS)
  const advance = Math.min(backlog, Math.max(1, Math.round(rate * clampedDt)))
  return revealed + advance
}

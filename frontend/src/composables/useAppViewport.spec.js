import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

const lifecycle = vi.hoisted(() => ({
  mounted: null,
  beforeUnmount: null,
}))

vi.mock('vue', () => ({
  onMounted: (callback) => {
    lifecycle.mounted = callback
  },
  onBeforeUnmount: (callback) => {
    lifecycle.beforeUnmount = callback
  },
}))

import { useAppViewport } from './useAppViewport'

function createEventTarget() {
  const listeners = new Map()
  return {
    addEventListener: vi.fn((type, callback) => listeners.set(type, callback)),
    removeEventListener: vi.fn((type, callback) => {
      if (listeners.get(type) === callback) {
        listeners.delete(type)
      }
    }),
    dispatch(type) {
      listeners.get(type)?.()
    },
    listener(type) {
      return listeners.get(type)
    },
  }
}

function installDomMocks({ withVisualViewport = true } = {}) {
  const visualViewport = Object.assign(createEventTarget(), {
    height: 844,
    scale: 1,
  })
  const windowTarget = createEventTarget()
  const windowMock = Object.assign(windowTarget, {
    scrollY: 0,
    scrollTo: vi.fn(),
  })
  if (withVisualViewport) {
    windowMock.visualViewport = visualViewport
  }

  const setProperty = vi.fn()
  vi.stubGlobal('window', windowMock)
  vi.stubGlobal('document', {
    documentElement: {
      style: { setProperty },
    },
  })

  return { setProperty, visualViewport, windowMock }
}

function mountComposable() {
  useAppViewport()
  lifecycle.mounted()
}

describe('useAppViewport', () => {
  beforeEach(() => {
    lifecycle.mounted = null
    lifecycle.beforeUnmount = null
  })

  afterEach(() => {
    vi.unstubAllGlobals()
    vi.clearAllMocks()
  })

  it('sets --app-height from visualViewport when mounted', () => {
    const { setProperty } = installDomMocks()

    mountComposable()

    expect(setProperty).toHaveBeenCalledWith('--app-height', '844px')
  })

  it('updates the app height and resets window panning on resize', () => {
    const { setProperty, visualViewport, windowMock } = installDomMocks()
    mountComposable()
    visualViewport.height = 620
    windowMock.scrollY = 48

    visualViewport.dispatch('resize')

    expect(setProperty).toHaveBeenLastCalledWith('--app-height', '620px')
    expect(windowMock.scrollTo).toHaveBeenCalledWith(0, 0)
  })

  it('does not update the app height while pinch zoomed', () => {
    const { setProperty, visualViewport } = installDomMocks()
    mountComposable()
    visualViewport.height = 420
    visualViewport.scale = 2

    visualViewport.dispatch('resize')

    expect(setProperty).toHaveBeenCalledTimes(1)
    expect(setProperty).not.toHaveBeenCalledWith('--app-height', '420px')
  })

  it('removes visualViewport and window listeners when unmounted', () => {
    const { visualViewport, windowMock } = installDomMocks()
    mountComposable()
    const resizeListener = visualViewport.listener('resize')
    const scrollListener = windowMock.listener('scroll')

    lifecycle.beforeUnmount()

    expect(visualViewport.removeEventListener).toHaveBeenCalledWith('resize', resizeListener)
    expect(windowMock.removeEventListener).toHaveBeenCalledWith('scroll', scrollListener)
    expect(visualViewport.listener('resize')).toBeUndefined()
    expect(windowMock.listener('scroll')).toBeUndefined()
  })

  it('does nothing when visualViewport is unavailable', () => {
    const { setProperty, windowMock } = installDomMocks({ withVisualViewport: false })

    mountComposable()

    expect(setProperty).not.toHaveBeenCalled()
    expect(windowMock.addEventListener).not.toHaveBeenCalled()
  })
})

import { onBeforeUnmount, onMounted, ref } from 'vue'

const KEYBOARD_MIN_DELTA_PX = 150

const appHeight = ref(null)
const keyboardOpen = ref(false)

export function useViewportState() {
  return { appHeight, keyboardOpen }
}

export function useAppViewport() {
  let visualViewport = null
  let maxViewportHeight = null
  let viewportWidth = null

  function resetWindowScroll() {
    if (window.scrollY > 0) {
      window.scrollTo(0, 0)
    }
  }

  function syncAppHeight() {
    if (visualViewport.scale <= 1) {
      const currentHeight = visualViewport.height
      const currentWidth = visualViewport.width

      if (viewportWidth !== currentWidth) {
        viewportWidth = currentWidth
        maxViewportHeight = currentHeight
      } else {
        maxViewportHeight = Math.max(maxViewportHeight ?? currentHeight, currentHeight)
      }

      appHeight.value = currentHeight
      keyboardOpen.value = window.matchMedia('(pointer: coarse)').matches
        && maxViewportHeight - currentHeight >= KEYBOARD_MIN_DELTA_PX

      document.documentElement.style.setProperty('--app-height', `${visualViewport.height}px`)
      if (keyboardOpen.value) {
        document.documentElement.setAttribute('data-keyboard', 'open')
      } else {
        document.documentElement.removeAttribute('data-keyboard')
      }
    }
    resetWindowScroll()
  }

  onMounted(() => {
    visualViewport = window.visualViewport
    if (!visualViewport) {
      return
    }

    syncAppHeight()
    visualViewport.addEventListener('resize', syncAppHeight)
    window.addEventListener('scroll', resetWindowScroll)
  })

  onBeforeUnmount(() => {
    if (visualViewport) {
      visualViewport.removeEventListener('resize', syncAppHeight)
      window.removeEventListener('scroll', resetWindowScroll)
    }

    document.documentElement.removeAttribute('data-keyboard')
    appHeight.value = null
    keyboardOpen.value = false
  })
}

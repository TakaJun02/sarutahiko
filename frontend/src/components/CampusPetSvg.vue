<script setup>
import { computed } from 'vue'

import { CAMPUS_PET_SVGS } from './campusPetSvgs'

const props = defineProps({
  form: {
    type: String,
    required: true,
  },
  state: {
    type: String,
    default: 'idle',
  },
  reaction: {
    type: String,
    default: '',
  },
})

const svgMarkup = computed(() => {
  const source = CAMPUS_PET_SVGS[props.form] || CAMPUS_PET_SVGS.robo
  const reactionAttribute = props.reaction ? ` data-reaction="${props.reaction}"` : ''
  return source.replace('data-state="idle"', `data-state="${props.state}"${reactionAttribute}`)
})
</script>

<template>
  <span class="campus-pet-renderer" aria-hidden="true" v-html="svgMarkup"></span>
</template>

<style>
.campus-pet-renderer {
  display: block;
  width: 100%;
  height: 100%;
  pointer-events: none;
}

.campus-pet-renderer > svg {
  display: block;
}
</style>

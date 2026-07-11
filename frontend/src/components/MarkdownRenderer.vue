<script setup>
import { computed } from 'vue'
import { marked } from 'marked'

const props = defineProps({
  content: {
    type: String,
    required: true,
  },
})

marked.setOptions({
  breaks: true,
  gfm: true,
})

const html = computed(() => marked.parse(props.content))
</script>

<template>
  <div class="markdown-body" v-html="html"></div>
</template>

<script setup lang="ts">
import { MotionConfig } from 'motion-v'
</script>

<template>
  <!-- reduced-motion="user": respects the system "reduce motion" preference and degrades every motion animation -->
  <MotionConfig reduced-motion="user">
    <router-view />
  </MotionConfig>
</template>

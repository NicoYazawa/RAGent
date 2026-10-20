<script setup lang="ts">
import { MotionConfig } from 'motion-v'
</script>

<template>
  <!-- reduced-motion="user"：尊重系统"减少动态效果"偏好，所有 motion 动画自动降级 -->
  <MotionConfig reduced-motion="user">
    <router-view />
  </MotionConfig>
</template>

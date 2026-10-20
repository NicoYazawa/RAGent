<script setup lang="ts">
import SideRail from './SideRail.vue'
</script>

<template>
  <div class="flex h-screen w-screen overflow-hidden bg-deep">
    <SideRail />

    <main class="min-w-0 flex-1 overflow-hidden pb-14 md:pb-0">
      <router-view v-slot="{ Component }">
        <transition name="page" mode="out-in">
          <component :is="Component" class="h-full" />
        </transition>
      </router-view>
    </main>
  </div>
</template>

<style scoped>
.page-enter-active,
.page-leave-active {
  transition: opacity 0.16s ease-out;
}
.page-enter-from,
.page-leave-to {
  opacity: 0;
}
</style>

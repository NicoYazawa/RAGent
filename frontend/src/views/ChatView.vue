<script setup lang="ts">
import { onMounted, ref, watch } from 'vue'
import SessionList from '@/components/chat/SessionList.vue'
import MessageList from '@/components/chat/MessageList.vue'
import ChatInput from '@/components/chat/ChatInput.vue'
import DecisionSidebar from '@/components/chat/DecisionSidebar.vue'
import Icon from '@/components/ui/Icon.vue'
import BaseTooltip from '@/components/ui/BaseTooltip.vue'
import { useI18n } from 'vue-i18n'
import { useChatStore } from '@/stores/chat'

/** 问答对话页：会话列表 / 对话区 / 决策过程侧栏 */
const { t } = useI18n()
const store = useChatStore()
const sidebarOpen = ref(true)
const sessionsOpen = ref(false)

onMounted(async () => {
  await store.loadSessions()
  if (store.sessions.length > 0) {
    await store.selectSession(store.sessions[0].id)
  }
})

// 手机抽屉：选中会话后收起
watch(
  () => store.currentSessionId,
  () => {
    sessionsOpen.value = false
  },
)
</script>

<template>
  <div class="flex h-full min-w-0">
    <SessionList class="hidden lg:flex" />

    <!-- 手机：会话抽屉 -->
    <div v-if="sessionsOpen" class="fixed inset-0 z-50 flex lg:hidden">
      <div class="absolute inset-0 bg-black/60" @click="sessionsOpen = false" />
      <SessionList class="relative z-10 flex" @select="sessionsOpen = false" />
    </div>

    <!-- 中栏 -->
    <div class="flex min-w-0 flex-1 flex-col">
      <header class="flex h-14 items-center gap-3 border-b border-edge px-4 md:px-6">
        <button
          type="button"
          class="flex h-8 w-8 shrink-0 items-center justify-center rounded-md text-ink-mute transition-colors hover:text-ink-dim lg:hidden"
          :aria-label="t('chat.session.title')"
          @click="sessionsOpen = true"
        >
          <Icon name="logs" :size="16" />
        </button>
        <div class="min-w-0">
          <h1 class="truncate text-[18px] font-semibold leading-tight text-ink">
            {{ store.currentSession ? store.currentSession.title : t('chat.view.noSession') }}
          </h1>
          <p v-if="store.currentSession" class="mt-0.5 font-mono text-[12px] leading-none text-ink-mute">
            #{{ store.currentSession.id }} · {{ t('chat.view.messagesCount', { n: store.messages.length }) }}
          </p>
        </div>
        <div class="flex-1" />
        <BaseTooltip :content="sidebarOpen ? t('chat.view.collapseSidebar') : t('chat.view.expandSidebar')">
          <button
            type="button"
            class="relative flex h-8 shrink-0 items-center gap-1.5 whitespace-nowrap rounded-full px-2 text-[12px] transition-colors duration-150 sm:px-3"
            :class="sidebarOpen ? 'text-ink' : 'text-ink-mute hover:text-ink-dim'"
            @click="sidebarOpen = !sidebarOpen"
          >
            <Icon name="panel-right" :size="14" />
            <span>{{ t('chat.msg.decisionChain') }}</span>
            <span v-if="sidebarOpen" class="absolute inset-x-3 -bottom-px h-px bg-accent" />
          </button>
        </BaseTooltip>
      </header>

      <MessageList />
      <ChatInput />
    </div>

    <!-- 右栏：决策过程（可折叠；手机隐藏） -->
    <Transition name="sidebar">
      <DecisionSidebar v-if="sidebarOpen || store.viewingLog" class="hidden lg:flex" />
    </Transition>
  </div>
</template>

<style scoped>
.sidebar-enter-active,
.sidebar-leave-active {
  transition:
    width 0.22s cubic-bezier(0.16, 1, 0.3, 1),
    opacity 0.18s ease-out;
  overflow: hidden;
}
.sidebar-enter-from,
.sidebar-leave-to {
  width: 0;
  opacity: 0;
}
</style>

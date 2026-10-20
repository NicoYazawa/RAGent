<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import Icon from '@/components/ui/Icon.vue'
import BaseToggle from '@/components/ui/BaseToggle.vue'
import BaseInput from '@/components/ui/BaseInput.vue'
import type { DatasourceItem, RetrievalSource } from '@/api/types'
import { sourceMeta } from '@/api/admin'

const { t } = useI18n()

/** 数据源卡片：开关 + 连接配置表单 */
const props = defineProps<{ item: DatasourceItem }>()
const emit = defineEmits<{ toggle: [enabled: boolean]; updateConfig: [key: string, value: string] }>()

const meta = computed(() => sourceMeta(props.item.source_type as RetrievalSource))
const configEntries = computed(() => Object.entries(props.item.config))
</script>

<template>
  <div class="flex flex-col rounded-lg border bg-card p-4" :class="item.enabled ? 'border-edge-bright' : 'border-edge'">
    <!-- 头部：图标 + 名称 + 开关 -->
    <div class="flex items-start justify-between gap-3">
      <div class="flex min-w-0 items-start gap-2.5">
        <Icon :name="meta?.icon ?? 'info'" :size="16" class="mt-0.5 shrink-0 text-ink-mute" />
        <div class="min-w-0">
          <div class="flex items-center gap-2">
            <h2 class="text-[14px] font-medium text-ink">{{ meta?.label ?? item.source_type }}</h2>
            <span class="rounded border border-edge px-1 font-mono text-[11px] text-ink-mute">{{ item.source_type }}</span>
          </div>
          <p class="mt-1 text-[13px] leading-relaxed text-ink-mute">{{ meta?.desc }}</p>
        </div>
      </div>
      <div class="flex shrink-0 flex-col items-end gap-1.5">
        <BaseToggle :model-value="item.enabled" @update:model-value="(v) => emit('toggle', v)" />
        <span class="text-[11px]" :class="item.enabled ? 'text-ok' : 'text-ink-mute'">
          {{ item.enabled ? 'Enabled' : 'Disabled' }}
        </span>
      </div>
    </div>

    <!-- 连接配置 -->
    <div class="mt-4 flex-1 space-y-2 border-t border-edge pt-3.5" :class="{ 'pointer-events-none opacity-50': !item.enabled }">
      <div v-for="[key, value] in configEntries" :key="key" class="flex items-center gap-2.5">
        <label class="w-32 shrink-0 truncate text-right font-mono text-[11px] text-ink-mute" :title="key">{{ key }}</label>
        <div class="min-w-0 flex-1">
          <BaseInput :model-value="value" mono :disabled="!item.enabled" @update:model-value="(v) => emit('updateConfig', key, v)" />
        </div>
      </div>
      <p class="pl-[138px] text-[11px] text-ink-mute">{{ t('datasource.secretNote') }}</p>
    </div>
  </div>
</template>

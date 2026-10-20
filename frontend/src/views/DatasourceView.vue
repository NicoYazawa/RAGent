<script setup lang="ts">
import { onMounted } from 'vue'
import { useI18n } from 'vue-i18n'
import Icon from '@/components/ui/Icon.vue'
import BaseButton from '@/components/ui/BaseButton.vue'
import SourceCard from '@/components/admin/SourceCard.vue'
import { useDatasourceStore } from '@/stores/datasource'

const { t } = useI18n()

/** 数据源配置页：三类检索源开关卡片 + 连接配置 */
const store = useDatasourceStore()

onMounted(() => void store.load())

function onToggle(index: number, enabled: boolean): void {
  store.items[index].enabled = enabled
}

function onUpdateConfig(index: number, key: string, value: string): void {
  store.items[index].config[key] = value
}

const enabledCount = () => store.items.filter((i) => i.enabled).length
</script>

<template>
  <div class="h-full overflow-y-auto">
    <div class="mx-auto max-w-5xl px-4 py-6 md:px-8">
      <!-- 页头 -->
      <div class="mb-6 flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 class="text-[24px] font-semibold leading-tight text-ink">
            {{ t('datasource.title') }}
          </h1>
          <p class="mt-1.5 max-w-2xl text-[13px] leading-relaxed text-ink-mute">
            {{ t('datasource.intro') }}
          </p>
        </div>
        <div class="flex items-center gap-3">
          <span v-if="store.savedAt" class="font-mono text-[11px] text-ok">{{ t('datasource.saved', { time: store.savedAt }) }}</span>
          <BaseButton :loading="store.saving" :disabled="store.loading" @click="store.save()">
            <Icon name="check" :size="13" /> {{ t('datasource.saveConfig') }}
          </BaseButton>
        </div>
      </div>

      <!-- 卡片网格：三个数据源固定三列，不留空位 -->
      <div v-if="store.loading" class="grid gap-4 md:grid-cols-3">
        <div v-for="i in 3" :key="i" class="h-[190px] animate-pulse rounded-lg border border-edge bg-card" />
      </div>

      <div v-else class="grid gap-4 md:grid-cols-3">
        <SourceCard
          v-for="(item, i) in store.items"
          :key="item.source_type"
          :item="item"
          @toggle="(v) => onToggle(i, v)"
          @update-config="(k, v) => onUpdateConfig(i, k, v)"
        />
      </div>

      <!-- 说明区 -->
      <div class="mt-6 grid gap-3 rounded-xl border border-edge bg-panel/70 p-4 text-[13px] leading-relaxed text-ink-dim md:grid-cols-2">
        <div class="flex gap-2">
          <Icon name="info" :size="14" class="mt-0.5 shrink-0 text-ink-mute" />
          <p><span class="text-ink">{{ t('datasource.leadVector') }}</span>{{ t('datasource.bodyVector') }}</p>
        </div>
        <div class="flex gap-2">
          <Icon name="db" :size="14" class="mt-0.5 shrink-0 text-src-db" />
          <p><span class="text-ink">{{ t('datasource.leadDb') }}</span>{{ t('datasource.bodyDb') }}</p>
        </div>
        <div class="flex gap-2">
          <Icon name="zap" :size="14" class="mt-0.5 shrink-0 text-warn" />
          <p><span class="text-ink">{{ t('datasource.leadScope') }}</span>{{ t('datasource.bodyScope', { n: enabledCount() }) }}</p>
        </div>
      </div>
    </div>
  </div>
</template>

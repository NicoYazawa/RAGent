<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import type { Citation } from '@/api/types'
import { citationNumber } from '@/utils/citations'

/**
 * 轻量 Markdown 渲染（自研，避免外部依赖）
 * 支持：标题 / 加粗 / 行内代码 / 围栏代码块 / 表格 / 列表 / 引用块 / 链接 / 分隔线 / [n] 引用角标
 * [n] 角标可点击（事件委托），由父组件联动引用卡片定位
 */
const props = defineProps<{ text: string; citations?: Citation[] }>()
const emit = defineEmits<{ citeClick: [n: number] }>()
const { t } = useI18n()
const referenceNumbers = computed(() => new Set(props.citations?.map((c, i) => citationNumber(c, i, props.text))))

function escapeHtml(s: string): string {
  return s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;')
}

function inline(s: string): string {
  let out = escapeHtml(s)
  // [n] 引用角标（仅当该序号存在于 citations 中才可点击）
  out = out.replace(/\[(\d+)\]/g, (_m, n: string) => {
    const idx = Number(n)
    const exists = !props.citations || referenceNumbers.value.has(idx)
    return exists
      ? `<button type="button" class="cite-mark" data-n="${idx}" title="${t('chat.msg.viewCite')}">[${idx}]</button>`
      : `<span class="text-ink-mute">[${idx}]</span>`
  })
  out = out.replace(/\*\*([^*]+)\*\*/g, '<strong class="font-semibold text-ink">$1</strong>')
  out = out.replace(/`([^`]+)`/g, '<code class="mx-0.5 rounded bg-raise px-1.5 py-0.5 font-mono text-[12px] text-accent-soft">$1</code>')
  // 链接（仅允许 http/https，防 javascript: 注入）
  out = out.replace(
    /\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)/g,
    '<a href="$2" target="_blank" rel="noopener noreferrer" class="text-accent underline decoration-accent/40 underline-offset-2 hover:decoration-accent">$1</a>',
  )
  return out
}

// 标题层级样式（正文 13px 基准，层级递减，与气泡内排版协调）
const HEADING_CLASS: Record<number, string> = {
  1: 'mt-3 mb-1.5 text-[16px]',
  2: 'mt-3 mb-1 text-[15px]',
  3: 'mt-2.5 mb-1 text-[14px]',
  4: 'mt-2 mb-0.5 text-[13.5px]',
  5: 'mt-2 mb-0.5 text-[13.5px]',
  6: 'mt-2 mb-0.5 text-[13.5px]',
}

const html = computed(() => {
  const lines = props.text.split('\n')
  const out: string[] = []
  let i = 0
  while (i < lines.length) {
    const line = lines[i]
    if (line.trim().startsWith('```')) {
      // 围栏代码块（流式未闭合时渲染到末尾，内容原样转义不做行内渲染）
      const lang = line.trim().slice(3).trim()
      i++
      const buf: string[] = []
      while (i < lines.length && !lines[i].trim().startsWith('```')) {
        buf.push(lines[i])
        i++
      }
      i++ // 跳过收束 ```
      out.push(
        `<div class="my-2 overflow-hidden rounded-lg border border-edge bg-raise">` +
          (lang ? `<div class="border-b border-edge px-3 py-1 font-mono text-[11px] text-ink-mute">${escapeHtml(lang)}</div>` : '') +
          `<pre class="overflow-x-auto px-3 py-2.5 text-[13px] leading-relaxed"><code class="font-mono text-ink-dim">${escapeHtml(buf.join('\n'))}</code></pre>` +
          `</div>`,
      )
    } else if (/^#{1,6}\s*\S/.test(line.trim())) {
      // 标题（# ~ ######，兼容中文模型省略空格的「###一、」写法）
      const m = line.trim().match(/^(#{1,6})\s*(.+)$/)!
      const lv = m[1].length
      out.push(`<h${lv} class="${HEADING_CLASS[lv]} font-semibold text-ink">${inline(m[2])}</h${lv}>`)
      i++
    } else if (/^(-{3,}|\*{3,})$/.test(line.trim())) {
      // 分隔线（表头分隔行由表格分支先消费，不会走到这里）
      out.push('<hr class="my-3 border-edge" />')
      i++
    } else if (line.trim().startsWith('|') && i + 1 < lines.length && /^\|[\s:|-]+\|?$/.test(lines[i + 1].trim())) {
      // 表格块
      const header = line.split('|').slice(1, -1).map((c) => c.trim())
      i += 2
      const rows: string[][] = []
      while (i < lines.length && lines[i].trim().startsWith('|')) {
        rows.push(lines[i].split('|').slice(1, -1).map((c) => c.trim()))
        i++
      }
      out.push(
        `<div class="my-2 overflow-x-auto rounded-lg border border-edge"><table class="w-full min-w-[420px] text-left text-[13px]">` +
          `<thead class="bg-raise text-ink"><tr>${header.map((h) => `<th class="px-3 py-2 font-medium">${inline(h)}</th>`).join('')}</tr></thead>` +
          `<tbody class="text-ink-dim">${rows.map((r) => `<tr class="border-t border-edge">${r.map((c) => `<td class="px-3 py-2">${inline(c)}</td>`).join('')}</tr>`).join('')}</tbody>` +
          `</table></div>`,
      )
    } else if (line.trimStart().startsWith('> ')) {
      // 引用块（声明/警示）
      const buf: string[] = []
      while (i < lines.length && lines[i].trimStart().startsWith('> ')) {
        buf.push(lines[i].trimStart().slice(2))
        i++
      }
      out.push(
        `<div class="my-2 rounded-lg border border-edge border-l-2 border-l-warn bg-card px-3 py-2 text-[13px] leading-relaxed text-ink-dim"><div>${buf.map((b) => inline(b)).join('<br/>')}</div></div>`,
      )
    } else if (/^\d+\.\s/.test(line.trim())) {
      // 有序列表
      const buf: string[] = []
      while (i < lines.length && /^\d+\.\s/.test(lines[i].trim())) {
        buf.push(lines[i].trim().replace(/^\d+\.\s/, ''))
        i++
      }
      out.push(`<ol class="my-1.5 ml-5 list-decimal space-y-1 text-[13px] leading-relaxed">${buf.map((b) => `<li>${inline(b)}</li>`).join('')}</ol>`)
    } else if (line.trim().startsWith('- ')) {
      // 无序列表
      const buf: string[] = []
      while (i < lines.length && lines[i].trim().startsWith('- ')) {
        buf.push(lines[i].trim().slice(2))
        i++
      }
      out.push(`<ul class="my-1.5 ml-5 list-disc space-y-1 text-[13px] leading-relaxed">${buf.map((b) => `<li>${inline(b)}</li>`).join('')}</ul>`)
    } else if (line.trim() === '') {
      i++
    } else {
      out.push(`<p class="my-1.5 text-[13px] leading-relaxed">${inline(line)}</p>`)
      i++
    }
  }
  return out.join('')
})

function onClick(e: MouseEvent): void {
  const target = (e.target as HTMLElement).closest('.cite-mark')
  if (target) {
    emit('citeClick', Number((target as HTMLElement).dataset.n))
  }
}
</script>

<template>
  <!-- eslint-disable-next-line vue/no-v-html -->
  <div class="markdown-body text-ink-dim" @click="onClick" v-html="html" />
</template>

<style scoped>
.markdown-body :deep(.cite-mark) {
  margin: 0 2px;
  padding: 0 2px;
  font-family: var(--font-mono);
  font-size: 11px;
  vertical-align: super;
  line-height: 1;
  color: var(--color-ink-dim);
  border: 1px solid var(--color-edge-bright);
  border-radius: 3px;
  background: var(--color-raise);
  cursor: pointer;
  transition: color 0.15s ease-out, border-color 0.15s ease-out;
}
.markdown-body :deep(.cite-mark:hover) {
  color: var(--color-ink);
  border-color: var(--color-accent);
}
</style>

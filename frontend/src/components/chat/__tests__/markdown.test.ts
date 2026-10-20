import { describe, expect, it, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import type { Citation } from '@/api/types'

/**
 * MarkdownText —— 自研轻量 Markdown 渲染器。
 * 关键契约：
 *   - 标题 / 加粗 / 行内代码 / 围栏代码块 / 表格 / 列表 / 引用块 / 链接 / 分隔线
 *   - HTML 必须转义（防止注入）
 *   - 链接只允许 http/https（javascript: 不得生成 <a>）
 *   - [n] 引用角标：citations 里存在该序号才可点击，点击抛出 citeClick
 */

vi.mock('vue-i18n', async (importOriginal) => {
  const { createI18nMock } = await import('@/test/i18nMock')
  return createI18nMock(importOriginal)
})

import MarkdownText from '../MarkdownText.vue'

const cite = (n: number): Citation => ({ doc_name: `d${n}.md`, section_path: 'p', chunk_no: n })

const render = (text: string, citations?: Citation[]) =>
  mount(MarkdownText, { props: { text, citations } })

describe('MarkdownText · 基础块级语法', () => {
  it('普通文本渲染为段落', () => {
    const w = render('hello world')
    expect(w.html()).toContain('<p class="my-1.5 text-[13px] leading-relaxed">hello world</p>')
  })

  it('空行不产生内容', () => {
    const w = render('\n\n')
    expect(w.html()).not.toContain('<p')
  })

  it('一级到六级标题渲染对应标签', () => {
    expect(render('# 一级').html()).toContain('<h1')
    expect(render('## 二级').html()).toContain('<h2')
    expect(render('### 三级').html()).toContain('<h3')
    expect(render('#### 四级').html()).toContain('<h4')
    expect(render('##### 五级').html()).toContain('<h5')
    expect(render('###### 六级').html()).toContain('<h6')
  })

  it('标题后省略空格的写法也能识别（中文模型常见）', () => {
    expect(render('###一、总则').html()).toContain('<h3')
  })

  it('分隔线渲染 hr', () => {
    expect(render('---').html()).toContain('<hr')
    expect(render('***').html()).toContain('<hr')
  })

  it('有��列表渲染为 ul/li', () => {
    const w = render('- 第一项\n- 第二项')
    expect(w.html()).toContain('<ul')
    expect(w.html()).toContain('<li>第一项</li>')
    expect(w.html()).toContain('<li>第二项</li>')
  })

  it('有序列表渲染为 ol/li 并去掉序号前缀', () => {
    const w = render('1. 第一步\n2. 第二步')
    expect(w.html()).toContain('<ol')
    expect(w.html()).toContain('<li>第一步</li>')
  })

  it('引用块渲染为警示样式容器', () => {
    const w = render('> 这是声明')
    expect(w.html()).toContain('border-l-warn')
    expect(w.html()).toContain('这是声明')
  })

  it('连续引用块合并为一个容器', () => {
    const w = render('> 第一行\n> 第二行')
    expect(w.html().match(/border-l-warn/g)?.length).toBe(1)
    expect(w.text()).toContain('第一行')
    expect(w.text()).toContain('第二行')
  })
})

describe('MarkdownText · 行内语法', () => {
  it('加粗渲染 strong', () => {
    expect(render('**重点**').html()).toContain('<strong class="font-semibold text-ink">重点</strong>')
  })

  it('行内代码渲染 code', () => {
    expect(render('`code`').html()).toContain('<code class="mx-0.5')
  })

  it('http 链接渲染为 a 且带安全属性', () => {
    const w = render('[官网](https://example.com)')
    expect(w.html()).toContain('href="https://example.com"')
    expect(w.html()).toContain('rel="noopener noreferrer"')
    expect(w.html()).toContain('target="_blank"')
  })

  it('javascript: 链接不会被渲染成可点击链接', () => {
    const w = render('[点我](javascript:alert(1))')
    expect(w.html()).not.toContain('href="javascript:')
  })

  it('html 标签被转义', () => {
    const w = render('<script>alert(1)</script>')
    expect(w.html()).not.toContain('<script>')
    expect(w.html()).toContain('&lt;script&gt;')
  })

  it('引号被转义（不会破坏 HTML 结构）', () => {
    const w = render('say "hi"')
    expect(w.text()).toContain('say "hi"')
  })
})

describe('MarkdownText · 代码块', () => {
  it('围栏代码块带语言标签', () => {
    const w = render('```python\nprint(1)\n```')
    expect(w.html()).toContain('python')
    expect(w.html()).toContain('print(1)')
    expect(w.html()).toContain('<pre')
  })

  it('围栏代码块无语言时不显示语言栏', () => {
    const w = render('```\nraw\n```')
    expect(w.html()).toContain('raw')
    expect(w.html()).not.toContain('border-b border-edge px-3 py-1 font-mono')
  })

  it('未闭合的围栏（流式输出中）也渲染到末尾', () => {
    const w = render('```js\nconst a = 1')
    expect(w.html()).toContain('const a = 1')
  })

  it('代码块内容不再做行内渲染', () => {
    const w = render('```\n**not bold**\n```')
    expect(w.html()).not.toContain('<strong')
    expect(w.html()).toContain('**not bold**')
  })
})

describe('MarkdownText · 表格', () => {
  it('渲染表头与数据行', () => {
    const w = render('| 名称 | 数量 |\n| --- | --- |\n| 苹果 | 3 |')
    expect(w.html()).toContain('<th class="px-3 py-2 font-medium">名称</th>')
    expect(w.html()).toContain('<td class="px-3 py-2">苹果</td>')
    expect(w.html()).toContain('<td class="px-3 py-2">3</td>')
  })

  it('表格分隔行不会单独渲染成 hr', () => {
    const w = render('| a | b |\n| --- | --- |\n| 1 | 2 |')
    expect(w.html()).not.toContain('<hr')
  })
})

describe('MarkdownText · 引用角标', () => {
  it('uses explicit sparse reference numbers instead of array positions', async () => {
    const w = render('third [3], first [1]', [{ ...cite(3), ref_id: 3 }, { ...cite(1), ref_id: 1 }])
    expect(w.findAll('button.cite-mark').map((b) => b.attributes('data-n'))).toEqual(['3', '1'])
    await w.find('[data-n="3"]').trigger('click')
    expect(w.emitted('citeClick')?.[0]).toEqual([3])
  })

  it('infers legacy sparse reference numbers from first appearance in the answer', () => {
    const w = render('third [3], first [1], third [3]', [cite(3), cite(1)])
    expect(w.findAll('button.cite-mark').map((b) => b.attributes('data-n'))).toEqual(['3', '1', '3'])
  })
  it('序号存在于 citations 时渲染可点击按钮', () => {
    const w = render('结论 [1]', [cite(1)])
    expect(w.html()).toContain('data-n="1"')
    expect(w.html()).toContain('cite-mark')
  })

  it('序号不存在于 citations 时渲染为普通文本', () => {
    const w = render('结论 [3]', [{ ...cite(1), ref_id: 1 }])
    expect(w.html()).not.toContain('cite-mark')
    expect(w.html()).toContain('[3]')
  })

  it('未提供 citations 时所有角标都可点击', () => {
    const w = render('结论 [2]')
    expect(w.html()).toContain('data-n="2"')
  })

  it('点击角标抛出 citeClick 与序号', async () => {
    const w = render('结论 [1]', [cite(1)])
    await w.find('button.cite-mark').trigger('click')
    expect(w.emitted('citeClick')?.[0]).toEqual([1])
  })

  it('点击非角标内容不触发 citeClick', async () => {
    const w = render('普通文本', [cite(1)])
    await w.trigger('click')
    expect(w.emitted('citeClick')).toBeUndefined()
  })
})


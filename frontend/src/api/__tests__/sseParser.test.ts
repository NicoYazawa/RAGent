import { describe, expect, it } from 'vitest'
import { SseParser } from '../sseParser'
import type { SseEvent } from '../types'

/** The payload fields vary with the event name, so any field is read here. */
const field = (e: SseEvent, key: string): unknown => (e as unknown as Record<string, unknown>)[key]

/**
 * SSE parser — the heart of the Q&A stream.
 * Backend event format: `event: <type>\ndata: {json}\n\n`
 * A parse error means the frontend "never receives the answer", so this covers cross-chunk buffering,
 * CRLF normalization, skipping invalid JSON and merging multi-line data.
 */
describe('SseParser', () => {
  it('解析单个完整事件', () => {
    const p = new SseParser()
    const events = p.feed('event: retrieve\ndata: {"step":3,"hit_count":2}\n\n')
    expect(events).toHaveLength(1)
    expect(events[0].type).toBe('retrieve')
    expect(events[0].step).toBe(3)
    expect(field(events[0], 'hit_count')).toBe(2)
  })

  it('未指定 event 名时默认为 message', () => {
    const p = new SseParser()
    const events = p.feed('data: {"a":1}\n\n')
    expect(events[0].type).toBe('message')
  })

  it('跨 chunk 缓存半截事件', () => {
    const p = new SseParser()
    expect(p.feed('event: generate\ndata: {"de')).toEqual([])
    expect(p.feed('lta":"你好"}\n')).toEqual([])
    const events = p.feed('\n')
    expect(events).toHaveLength(1)
    expect(events[0].type).toBe('generate')
    expect(field(events[0], 'delta')).toBe('你好')
  })

  it('一次 feed 多个事件', () => {
    const p = new SseParser()
    const events = p.feed('event: a\ndata: {"n":1}\n\nevent: b\ndata: {"n":2}\n\n')
    expect(events.map((e) => e.type)).toEqual(['a', 'b'])
  })

  it('把 CRLF 归一为 LF', () => {
    const p = new SseParser()
    const events = p.feed('event: done\r\ndata: {"ok":true}\r\n\r\n')
    expect(events).toHaveLength(1)
    expect(events[0].type).toBe('done')
    expect(field(events[0], 'ok')).toBe(true)
  })

  it('非法 JSON 的事件被跳过，不影响后续事件', () => {
    const p = new SseParser()
    const events = p.feed('event: bad\ndata: {不是 JSON}\n\nevent: good\ndata: {"ok":1}\n\n')
    expect(events).toHaveLength(1)
    expect(events[0].type).toBe('good')
  })

  it('没有 data 行的块被忽略', () => {
    const p = new SseParser()
    expect(p.feed('event: only-name\n\n')).toEqual([])
  })

  it('多行 data 按换行拼接后解析', () => {
    const p = new SseParser()
    const events = p.feed('event: multi\ndata: {"a":\ndata: 1}\n\n')
    expect(events).toHaveLength(1)
    expect(field(events[0], 'a')).toBe(1)
  })

  it('保留 payload 的全部字段', () => {
    const p = new SseParser()
    const events = p.feed('event: x\ndata: {"step":1,"detail":"命中","source":"vector","hit_count":3}\n\n')
    expect(events[0]).toMatchObject({
      type: 'x',
      step: 1,
      detail: '命中',
      source: 'vector',
      hit_count: 3,
    })
  })

  it('不完整的事件不会提前吐出', () => {
    const p = new SseParser()
    expect(p.feed('event: x\ndata: {"a":1}\n')).toEqual([])
  })
})


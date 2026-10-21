import type { SseEvent } from './types'

/* ============================================================
 * SSE text-stream parser — consumes fetch/ReadableStream from a POST JSON request
 * ============================================================ */

export class SseParser {
  private buffer = ''

  /** Feed incremental text and return the fully parsed events (buffers across chunks; \r\n is normalized to \n) */
  feed(text: string): SseEvent[] {
    this.buffer += text.replace(/\r\n/g, '\n')
    const events: SseEvent[] = []
    let idx: number
    while ((idx = this.buffer.indexOf('\n\n')) !== -1) {
      const block = this.buffer.slice(0, idx)
      this.buffer = this.buffer.slice(idx + 2)
      const event = this.parseBlock(block)
      if (event) events.push(event)
    }
    return events
  }

  private parseBlock(block: string): SseEvent | null {
    let eventName = 'message'
    const dataLines: string[] = []
    for (const line of block.split('\n')) {
      if (line.startsWith('event:')) {
        eventName = line.slice(6).trim()
      } else if (line.startsWith('data:')) {
        dataLines.push(line.slice(5).trimStart())
      }
    }
    if (dataLines.length === 0) return null
    try {
      const data = JSON.parse(dataLines.join('\n')) as Record<string, unknown>
      return { type: eventName, ...data } as unknown as SseEvent
    } catch {
      return null
    }
  }
}

// In-memory localStorage polyfill.
// Node 22's experimental localStorage needs --localstorage-file, and under CI or local jsdom
// the global localStorage is undefined; a deterministic in-memory implementation avoids environment drift.
class MemStorage {
  private m = new Map<string, string>()
  get length(): number {
    return this.m.size
  }
  key(i: number): string | null {
    return [...this.m.keys()][i] ?? null
  }
  getItem(k: string): string | null {
    return this.m.has(k) ? (this.m.get(k) as string) : null
  }
  setItem(k: string, v: string): void {
    this.m.set(k, String(v))
  }
  removeItem(k: string): void {
    this.m.delete(k)
  }
  clear(): void {
    this.m.clear()
  }
}

try {
  Object.defineProperty(globalThis, 'localStorage', {
    value: new MemStorage(),
    configurable: true,
    writable: true,
  })
} catch {
  // ignore it when already defined and non-configurable
}

// jsdom does not implement scroll-related DOM APIs used for auto-scroll/positioning, so empty stubs avoid test errors.
if (!Element.prototype.scrollTo) {
  Element.prototype.scrollTo = function scrollTo(): void {}
}
if (!Element.prototype.scrollIntoView) {
  Element.prototype.scrollIntoView = function scrollIntoView(): void {}
}

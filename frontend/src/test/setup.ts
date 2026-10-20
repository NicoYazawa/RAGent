// 内存版 localStorage polyfill。
// Node 22 的实验性 localStorage 需 --localstorage-file 才可用，CI/本地 jsdom 下
// 全局 localStorage 为 undefined；这里用一个确定性内存实现，避免环境差异。
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
  // 已被占用且不可重定义时忽略
}

// jsdom 不实现滚动相关 DOM API，组件里用于自动滚动/定位，补空实现避免测试报错。
if (!Element.prototype.scrollTo) {
  Element.prototype.scrollTo = function scrollTo(): void {}
}
if (!Element.prototype.scrollIntoView) {
  Element.prototype.scrollIntoView = function scrollIntoView(): void {}
}

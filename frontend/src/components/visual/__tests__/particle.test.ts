import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { mount } from '@vue/test-utils'

/**
 * 粒子背景（three.js）—— jsdom 无 WebGL，用替身 three 验证组件自身的
 * 生命周期契约：初始化、粒子/连线缓冲、指针视差、可见性暂停、资源释放。
 */

const threeState = vi.hoisted(() => ({
  rendered: 0,
  disposed: [] as string[],
  setSizeCalls: [] as Array<[number, number]>,
  positionBufferLength: 0,
  pixelRatio: 0,
  cameraAspect: 0,
}))

vi.mock('three', () => {
  class Vector3 {
    x = 0
    y = 0
    z = 0
    constructor(x = 0, y = 0, z = 0) {
      this.x = x
      this.y = y
      this.z = z
    }
    set(x: number, y: number, z: number) {
      this.x = x
      this.y = y
      this.z = z
      return this
    }
    distanceTo(other: Vector3) {
      return Math.hypot(this.x - other.x, this.y - other.y, this.z - other.z)
    }
  }
  class Color {
    r = 0
    g = 0
    b = 0
    constructor(hex: string) {
      if (hex === '#22d3ee') {
        this.r = 0.13
        this.g = 0.83
        this.b = 0.93
      } else {
        this.r = 0.4
        this.g = 0.9
        this.b = 0.98
      }
    }
  }
  class Scene {
    children: unknown[] = []
    add(o: unknown) {
      this.children.push(o)
    }
  }
  class PerspectiveCamera {
    position = new Vector3(0, 0, 0)
    aspect = 1
    updateProjectionMatrix() {}
    lookAt() {}
  }
  class WebGLRenderer {
    domElement = document.createElement('canvas')
    setPixelRatio(v: number) {
      threeState.pixelRatio = v
    }
    setSize(w: number, h: number) {
      threeState.setSizeCalls.push([w, h])
    }
    render() {
      threeState.rendered++
    }
    dispose() {
      threeState.disposed.push('renderer')
    }
  }
  class BufferAttribute {
    array: Float32Array
    needsUpdate = false
    constructor(array: Float32Array) {
      this.array = array
      if (threeState.positionBufferLength === 0) threeState.positionBufferLength = array.length
    }
  }
  class BufferGeometry {
    attributes: Record<string, BufferAttribute> = {}
    setAttribute(name: string, attr: BufferAttribute) {
      this.attributes[name] = attr
    }
    dispose() {
      threeState.disposed.push('geometry')
    }
  }
  class CanvasTexture {
    dispose() {
      threeState.disposed.push('texture')
    }
  }
  class PointsMaterial {
    dispose() {
      threeState.disposed.push('pointMaterial')
    }
  }
  class LineBasicMaterial {
    dispose() {
      threeState.disposed.push('lineMaterial')
    }
  }
  class Points {
    constructor(public geometry: unknown, public material: unknown) {}
  }
  class LineSegments {
    constructor(public geometry: unknown, public material: unknown) {}
  }
  return {
    Vector3,
    Color,
    Scene,
    PerspectiveCamera,
    WebGLRenderer,
    BufferAttribute,
    BufferGeometry,
    CanvasTexture,
    PointsMaterial,
    LineBasicMaterial,
    Points,
    LineSegments,
    AdditiveBlending: 2,
  }
})

import ParticleBackground from '../ParticleBackground.vue'

/** jsdom 无 canvas 2D 实现，补最小替身 */
function stubCanvas2D(): void {
  HTMLCanvasElement.prototype.getContext = vi.fn(() => ({
    fillStyle: '',
    beginPath: vi.fn(),
    arc: vi.fn(),
    fill: vi.fn(),
  })) as unknown as typeof HTMLCanvasElement.prototype.getContext
}

beforeEach(() => {
  // Vitest 默认不 fake requestAnimationFrame，这里显式接管，否则动画帧不会推进
  vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout', 'requestAnimationFrame', 'cancelAnimationFrame', 'Date'] })
  stubCanvas2D()
  threeState.rendered = 0
  threeState.disposed = []
  threeState.setSizeCalls = []
  threeState.positionBufferLength = 0
  threeState.pixelRatio = 0
  threeState.cameraAspect = 0
  // jsdom 的 clientWidth 恒为 0，这里给出确定尺寸以便断言粒子规模
  Object.defineProperty(HTMLElement.prototype, 'clientWidth', { configurable: true, value: 1200 })
  Object.defineProperty(HTMLElement.prototype, 'clientHeight', { configurable: true, value: 800 })
})

afterEach(() => {
  vi.useRealTimers()
})

describe('ParticleBackground', () => {
  it('挂载后把 WebGL canvas 插入容器', () => {
    const w = mount(ParticleBackground)
    expect(w.find('canvas').exists()).toBe(true)
  })

  it('按容器宽度决定粒子规模（宽屏 130 个粒子）', () => {
    mount(ParticleBackground)
    // 位置缓冲 = COUNT * 3
    expect(threeState.positionBufferLength).toBe(130 * 3)
  })

  it('窄屏容器使用 70 个粒子', () => {
    Object.defineProperty(HTMLElement.prototype, 'clientWidth', { configurable: true, value: 600 })
    mount(ParticleBackground)
    expect(threeState.positionBufferLength).toBe(70 * 3)
  })

  it('初始化时按设备像素比与容器尺寸设置渲染器', () => {
    mount(ParticleBackground)
    expect(threeState.pixelRatio).toBe(Math.min(window.devicePixelRatio, 2))
    expect(threeState.setSizeCalls[0]).toEqual([1200, 800])
  })

  it('动画帧驱动渲染', () => {
    mount(ParticleBackground)
    expect(threeState.rendered).toBe(0)
    vi.advanceTimersByTime(50)
    expect(threeState.rendered).toBeGreaterThan(0)
  })

  it('指针移动产生摄像机视差', () => {
    mount(ParticleBackground)
    vi.advanceTimersByTime(50)
    window.dispatchEvent(new MouseEvent('pointermove', { clientX: window.innerWidth, clientY: 0 }))
    vi.advanceTimersByTime(200)
    expect(threeState.rendered).toBeGreaterThan(1)
  })

  it('窗口尺寸变化时更新渲染器与投影', () => {
    mount(ParticleBackground)
    threeState.setSizeCalls = []
    window.dispatchEvent(new Event('resize'))
    expect(threeState.setSizeCalls.length).toBeGreaterThan(0)
  })

  it('页面隐藏时暂停动画，恢复可见后继续', () => {
    mount(ParticleBackground)
    vi.advanceTimersByTime(50)
    const before = threeState.rendered
    Object.defineProperty(document, 'visibilityState', { configurable: true, value: 'hidden' })
    document.dispatchEvent(new Event('visibilitychange'))
    vi.advanceTimersByTime(200)
    expect(threeState.rendered).toBe(before)
    Object.defineProperty(document, 'visibilityState', { configurable: true, value: 'visible' })
    document.dispatchEvent(new Event('visibilitychange'))
    vi.advanceTimersByTime(50)
    expect(threeState.rendered).toBeGreaterThan(before)
  })

  it('卸载时释放 GPU 资源并移除画布与监听器', () => {
    const w = mount(ParticleBackground)
    w.unmount()
    expect(threeState.disposed).toContain('renderer')
    expect(threeState.disposed).toContain('geometry')
    expect(threeState.disposed).toContain('pointMaterial')
    expect(threeState.disposed).toContain('lineMaterial')
    expect(threeState.disposed).toContain('texture')
    expect(document.querySelector('canvas')).toBeNull()
  })
})

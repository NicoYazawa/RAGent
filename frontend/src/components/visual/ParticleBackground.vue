<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref } from 'vue'
import * as THREE from 'three'

/**
 * 全屏知识节点网络背景：
 * - 青色粒子缓慢漂移，近邻节点自动连线（AdditiveBlending 叠加发光，无贴图渐变）
 * - 鼠标视差；页面隐藏自动暂停；组件卸载完整释放 GPU 资源
 */
const container = ref<HTMLDivElement>()

onMounted(() => {
  const el = container.value
  if (!el) return

  const ACCENT = new THREE.Color('#22d3ee')
  const ACCENT_SOFT = new THREE.Color('#67e8f9')

  const scene = new THREE.Scene()
  const camera = new THREE.PerspectiveCamera(60, el.clientWidth / el.clientHeight, 0.1, 100)
  camera.position.z = 26

  const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true })
  renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2))
  renderer.setSize(el.clientWidth, el.clientHeight)
  el.appendChild(renderer.domElement)

  /* ---------- 粒子 ---------- */
  const isNarrow = el.clientWidth < 900
  const COUNT = isNarrow ? 70 : 130
  const RANGE = { x: 46, y: 26, z: 14 } // 粒子活动空间
  const LINK_DIST = isNarrow ? 6.5 : 7.6 // 连线距离阈值

  const positions = new Float32Array(COUNT * 3)
  const colors = new Float32Array(COUNT * 3)
  const velocities: THREE.Vector3[] = []

  for (let i = 0; i < COUNT; i++) {
    positions[i * 3] = (Math.random() - 0.5) * RANGE.x * 2
    positions[i * 3 + 1] = (Math.random() - 0.5) * RANGE.y * 2
    positions[i * 3 + 2] = (Math.random() - 0.5) * RANGE.z * 2
    const c = Math.random() > 0.5 ? ACCENT : ACCENT_SOFT
    colors[i * 3] = c.r
    colors[i * 3 + 1] = c.g
    colors[i * 3 + 2] = c.b
    velocities.push(
      new THREE.Vector3((Math.random() - 0.5) * 0.022, (Math.random() - 0.5) * 0.022, (Math.random() - 0.5) * 0.012),
    )
  }

  const pointGeo = new THREE.BufferGeometry()
  pointGeo.setAttribute('position', new THREE.BufferAttribute(positions, 3))
  pointGeo.setAttribute('color', new THREE.BufferAttribute(colors, 3))

  // 实心圆粒子纹理（纯色圆点，非渐变）
  const dotCanvas = document.createElement('canvas')
  dotCanvas.width = 32
  dotCanvas.height = 32
  const ctx2d = dotCanvas.getContext('2d')!
  ctx2d.fillStyle = '#ffffff'
  ctx2d.beginPath()
  ctx2d.arc(16, 16, 13, 0, Math.PI * 2)
  ctx2d.fill()
  const dotTexture = new THREE.CanvasTexture(dotCanvas)

  const pointMat = new THREE.PointsMaterial({
    size: 0.52,
    map: dotTexture,
    vertexColors: true,
    transparent: true,
    opacity: 0.85,
    depthWrite: false,
    blending: THREE.AdditiveBlending,
    sizeAttenuation: true,
  })
  const points = new THREE.Points(pointGeo, pointMat)
  scene.add(points)

  /* ---------- 连线 ---------- */
  const MAX_LINKS = COUNT * 6
  const linePositions = new Float32Array(MAX_LINKS * 6)
  const lineColors = new Float32Array(MAX_LINKS * 6)
  const lineGeo = new THREE.BufferGeometry()
  lineGeo.setAttribute('position', new THREE.BufferAttribute(linePositions, 3))
  lineGeo.setAttribute('color', new THREE.BufferAttribute(lineColors, 3))
  const lineMat = new THREE.LineBasicMaterial({
    vertexColors: true,
    transparent: true,
    blending: THREE.AdditiveBlending,
    depthWrite: false,
  })
  const lines = new THREE.LineSegments(lineGeo, lineMat)
  scene.add(lines)

  /* ---------- 交互与循环 ---------- */
  let raf = 0
  let running = true
  const mouse = { x: 0, y: 0 }
  const camTarget = { x: 0, y: 0 }

  function onPointerMove(e: PointerEvent) {
    mouse.x = (e.clientX / window.innerWidth) * 2 - 1
    mouse.y = -(e.clientY / window.innerHeight) * 2 + 1
  }

  function onResize() {
    if (!el) return
    camera.aspect = el.clientWidth / el.clientHeight
    camera.updateProjectionMatrix()
    renderer.setSize(el.clientWidth, el.clientHeight)
  }

  function onVisibility() {
    running = document.visibilityState === 'visible'
    if (running) raf = requestAnimationFrame(tick)
  }

  const va = new THREE.Vector3()
  const vb = new THREE.Vector3()

  function tick() {
    if (!running) return
    raf = requestAnimationFrame(tick)

    // 粒子漂移 + 边界环绕
    for (let i = 0; i < COUNT; i++) {
      const v = velocities[i]
      let x = positions[i * 3] + v.x
      let y = positions[i * 3 + 1] + v.y
      let z = positions[i * 3 + 2] + v.z
      if (x > RANGE.x) x = -RANGE.x
      if (x < -RANGE.x) x = RANGE.x
      if (y > RANGE.y) y = -RANGE.y
      if (y < -RANGE.y) y = RANGE.y
      if (z > RANGE.z) z = -RANGE.z
      if (z < -RANGE.z) z = RANGE.z
      positions[i * 3] = x
      positions[i * 3 + 1] = y
      positions[i * 3 + 2] = z
    }
    pointGeo.attributes.position.needsUpdate = true

    // 近邻连线重建（颜色亮度随距离衰减，AdditiveBlending 下等效透明度）
    let li = 0
    for (let i = 0; i < COUNT && li < MAX_LINKS; i++) {
      va.set(positions[i * 3], positions[i * 3 + 1], positions[i * 3 + 2])
      for (let j = i + 1; j < COUNT && li < MAX_LINKS; j++) {
        vb.set(positions[j * 3], positions[j * 3 + 1], positions[j * 3 + 2])
        const dist = va.distanceTo(vb)
        if (dist < LINK_DIST) {
          const fade = 1 - dist / LINK_DIST
          const o = li * 6
          linePositions[o] = va.x
          linePositions[o + 1] = va.y
          linePositions[o + 2] = va.z
          linePositions[o + 3] = vb.x
          linePositions[o + 4] = vb.y
          linePositions[o + 5] = vb.z
          const r = 0.13 * fade
          const g = 0.83 * fade
          const b = 0.93 * fade
          lineColors[o] = r
          lineColors[o + 1] = g
          lineColors[o + 2] = b
          lineColors[o + 3] = r
          lineColors[o + 4] = g
          lineColors[o + 5] = b
          li++
        }
      }
    }
    // 未用满的连线顶点置黑（AdditiveBlending 下不可见）
    for (let k = li * 6; k < MAX_LINKS * 6; k++) {
      linePositions[k] = 0
      lineColors[k] = 0
    }
    lineGeo.attributes.position.needsUpdate = true
    lineGeo.attributes.color.needsUpdate = true

    // 摄像机视差缓动
    camTarget.x = mouse.x * 2.2
    camTarget.y = mouse.y * 1.4
    camera.position.x += (camTarget.x - camera.position.x) * 0.03
    camera.position.y += (camTarget.y - camera.position.y) * 0.03
    camera.lookAt(0, 0, 0)

    renderer.render(scene, camera)
  }

  window.addEventListener('resize', onResize)
  window.addEventListener('pointermove', onPointerMove)
  document.addEventListener('visibilitychange', onVisibility)
  raf = requestAnimationFrame(tick)

  /* ---------- 清理 ---------- */
  onBeforeUnmount(() => {
    running = false
    cancelAnimationFrame(raf)
    window.removeEventListener('resize', onResize)
    window.removeEventListener('pointermove', onPointerMove)
    document.removeEventListener('visibilitychange', onVisibility)
    pointGeo.dispose()
    pointMat.dispose()
    lineGeo.dispose()
    lineMat.dispose()
    dotTexture.dispose()
    renderer.dispose()
    renderer.domElement.remove()
  })
})
</script>

<template>
  <div ref="container" class="h-full w-full" />
</template>

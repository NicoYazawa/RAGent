import { describe, expect, it } from 'vitest'
import { readdirSync, readFileSync, statSync } from 'node:fs'
import { join, relative } from 'node:path'
import { fileURLToPath } from 'node:url'
import ts from 'typescript'

/**
 * Test-quality meta test (frontend counterpart of backend tests/test_test_quality.py)
 * Guards against "fake data passes" regressions:
 *   1. always-true assertions: expect(true) / expect(false) / expect(x).toBe(x)
 *   2. empty tests: the it/test callback body has no statements
 *   3. empty test files
 *   4. reading .env directly (tests must not depend on a local secret file)
 */

const SRC = join(process.cwd(), 'src')

function walk(dir: string): string[] {
  const out: string[] = []
  for (const name of readdirSync(dir)) {
    const p = join(dir, name)
    if (statSync(p).isDirectory()) {
      if (name === 'node_modules' || name === 'dist' || name === 'coverage') continue
      out.push(...walk(p))
    } else if (/\.test\.ts$/.test(name)) {
      out.push(p)
    }
  }
  return out
}

const TEST_FILES = walk(SRC)

/** Normalized text of an expression in the source. */
function exprText(node: ts.Node): string {
  return node.getText().replace(/\s+/g, ' ')
}

function findViolations(file: string): string[] {
  const text = readFileSync(file, 'utf8')
  const sf = ts.createSourceFile(file, text, ts.ScriptTarget.Latest, true)
  const problems: string[] = []
  const rel = relative(process.cwd(), file)

  const visit = (node: ts.Node): void => {
    // 1) always-true assertions
    if (ts.isCallExpression(node) && ts.isIdentifier(node.expression) && node.expression.text === 'expect') {
      const arg = node.arguments[0]
      if (arg && (arg.kind === ts.SyntaxKind.TrueKeyword || arg.kind === ts.SyntaxKind.FalseKeyword)) {
        problems.push(`${rel}: expect(${arg.getText()}) 恒真断言`)
      }
      // expect(x).toBe(x) / .toEqual(x) — self comparison
      const parent = node.parent
      if (arg && ts.isPropertyAccessExpression(parent) && ts.isCallExpression(parent.parent)) {
        const matcher = parent.name.text
        if ((matcher === 'toBe' || matcher === 'toEqual') && parent.parent.arguments.length > 0) {
          const other = parent.parent.arguments[0]
          if (other && exprText(other) === exprText(arg)) {
            problems.push(`${rel}: expect(${exprText(arg)}).${matcher}(...) 自比较`)
          }
        }
      }
    }

    // 2) empty test bodies
    if (ts.isCallExpression(node) && ts.isIdentifier(node.expression) && ['it', 'test'].includes(node.expression.text)) {
      const cb = node.arguments.find((a) => ts.isArrowFunction(a) || ts.isFunctionExpression(a))
      if (cb && ts.isArrowFunction(cb)) {
        const body = cb.body
        const empty =
          ts.isBlock(body) ? body.statements.length === 0 : ts.isIdentifier(body) && body.text === 'undefined'
        if (empty) {
          problems.push(`${rel}: ${node.expression.text}() 测试体为空`)
        }
      }
    }

    ts.forEachChild(node, visit)
  }
  visit(sf)
  return problems
}

describe('前端测试质量元测试', () => {
  it('能发现测试文件', () => {
    expect(TEST_FILES.length).toBeGreaterThan(10)
  })

  it('不存在恒真断言与自比较', () => {
    const problems = TEST_FILES.flatMap(findViolations)
    expect(problems, problems.join('\n')).toEqual([])
  })

  it('没有空的测试文件', () => {
    const empty = TEST_FILES.filter((f) => {
      const text = readFileSync(f, 'utf8')
      return !/\b(it|test)\s*\(/.test(text)
    })
    expect(empty.map((f) => relative(process.cwd(), f))).toEqual([])
  })

  it('测试不直接读取 .env（避免依赖本地密钥）', () => {
    const offenders: string[] = []
    const self = relative(process.cwd(), fileURLToPath(import.meta.url))
    for (const f of TEST_FILES) {
      if (relative(process.cwd(), f) === self) continue // this file contains the rules themselves
      const text = readFileSync(f, 'utf8')
      if (/(readFileSync|readFile)\s*\([^)]*\.env/.test(text) || /load_dotenv/.test(text)) {
        offenders.push(relative(process.cwd(), f))
      }
    }
    expect(offenders).toEqual([])
  })
})

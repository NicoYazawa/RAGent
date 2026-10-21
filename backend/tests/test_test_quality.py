"""测试套件自身的质量关卡（meta-test）

审计发现的历史问题里，最危险的一类是**恒真断言**——断言写错了但永远通过，
于是"测试全绿"与"功能正确"彻底脱钩。典型反例：

    assert ("reflect", {"result": "fail"}) or any(t == "reflect" for t in types)

左边是非空元组，恒为真，`or` 短路，右边根本不执行 → 这条断言等于没写。

本文件用 AST 静态检查把这类问题**拦在 CI 之前**：
  1. 恒真字面量断言（assert 非空容器 / 非零数 / True）
  2. or 短路恒真（左侧是无条件为真的字面量）
  3. 自比较（assert x == x）
  4. 空测试（函数体里没有任何断言 / pytest.raises）
  5. 空测试文件
"""
import ast
from pathlib import Path

TESTS_DIR = Path(__file__).resolve().parent
# this file contains AST sample data itself, so it is excluded from the scan to avoid self-reference
SELF = Path(__file__).name
# async functions are AsyncFunctionDef in ast (a sibling of FunctionDef, not a subclass)
FUNC_TYPES = (ast.FunctionDef, ast.AsyncFunctionDef)


def _read(path: Path) -> str:
    """Read with utf-8-sig to tolerate a BOM (Windows PowerShell writes one)."""
    return path.read_text(encoding="utf-8-sig")


def _test_files():
    return sorted(p for p in TESTS_DIR.glob("test_*.py") if p.name != SELF)


def _always_truthy(node: ast.AST) -> bool:
    """Decide whether an expression is unconditionally truthy (non-empty container / non-zero number /
    True / non-empty string)."""
    if isinstance(node, ast.Constant):
        v = node.value
        if v is True:
            return True
        if isinstance(v, (int, float)) and v != 0:
            return True
        if isinstance(v, str) and v:
            return True
        if v is None:
            return False
        return False
    if isinstance(node, (ast.Tuple, ast.List, ast.Set)):
        return len(node.elts) > 0
    if isinstance(node, ast.Dict):
        return len(node.keys) > 0
    return False


def _has_real_assertion(func: ast.FunctionDef) -> bool:
    """Whether the function body has a real assertion (an assert or a pytest.raises/warns context)."""
    for child in ast.walk(func):
        if isinstance(child, ast.Assert):
            return True
        if isinstance(child, ast.With):
            for item in child.items:
                ctx = item.context_expr
                if isinstance(ctx, ast.Call):
                    f = ctx.func
                    name = getattr(f, "attr", None) or getattr(f, "id", None)
                    if name in ("raises", "warns"):
                        return True
    return False


# ---------- 1. Always-true literal assertions ----------

def test_no_always_truthy_assertions():
    """Forbid always-true assertions such as assert <non-empty literal>."""
    bad = []
    for path in _test_files():
        tree = ast.parse(_read(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Assert):
                continue
            if _always_truthy(node.test):
                bad.append(f"{path.name}:{node.lineno}")
    assert not bad, "恒真断言（永远通过，等于没断言）：\n  " + "\n  ".join(bad)


# ---------- 2. Always-true or short circuit ----------

def test_no_short_circuit_tautology():
    """Forbid `assert <always-true literal> or <expression>` — the right side never runs."""
    bad = []
    for path in _test_files():
        tree = ast.parse(_read(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Assert):
                continue
            test = node.test
            if isinstance(test, ast.BoolOp) and isinstance(test.op, ast.Or) \
                    and test.values and _always_truthy(test.values[0]):
                bad.append(f"{path.name}:{node.lineno}")
    assert not bad, "or 短路恒真（右侧断言永不执行）：\n  " + "\n  ".join(bad)


# ---------- 3. Self comparison ----------

def test_no_self_comparison():
    """Forbid assert x == x (a variable compared with itself is always true).

    Only plain references (Name/Attribute) are covered; assertions such as `assert f() is f()` that
    verify a singleton cache are meaningful and are not flagged.
    """
    bad = []
    pure = (ast.Name, ast.Attribute)
    for path in _test_files():
        tree = ast.parse(_read(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Assert):
                continue
            test = node.test
            if isinstance(test, ast.Compare) and len(test.ops) == 1:
                left, right = test.left, test.comparators[0]
                if isinstance(left, pure) and isinstance(right, pure) \
                        and ast.dump(left) == ast.dump(right):
                    bad.append(f"{path.name}:{node.lineno}")
    assert not bad, "自比较断言（恒真）：\n  " + "\n  ".join(bad)


# ---------- 4. Empty tests ----------

def test_no_empty_test_functions():
    """Forbid test functions without any assertion (they always pass)."""
    bad = []
    for path in _test_files():
        tree = ast.parse(_read(path))
        for node in ast.walk(tree):
            if not isinstance(node, FUNC_TYPES):
                continue
            if not node.name.startswith("test_"):
                continue
            if not _has_real_assertion(node):
                bad.append(f"{path.name}:{node.lineno} {node.name}")
    assert not bad, "空测试（无任何断言，永远通过）：\n  " + "\n  ".join(bad)


# ---------- 5. Empty test files ----------

def test_no_empty_test_files():
    """Forbid files without any test function."""
    bad = []
    for path in _test_files():
        tree = ast.parse(_read(path))
        has_test = any(
            isinstance(n, FUNC_TYPES) and n.name.startswith("test_")
            for n in ast.walk(tree)
        )
        if not has_test:
            bad.append(path.name)
    assert not bad, f"没有测试的文件：{bad}"


# ---------- 6. Test files must not depend on a local .env ----------

def test_tests_do_not_read_env_file_directly():
    """Tests must not read backend/.env directly (environment coupling makes results machine dependent).

    Only code that really reads the file is flagged; explaining .env semantics in a docstring is fine.
    """
    bad = []
    read_patterns = ("open(", "read_text(", "read_bytes(", "load_dotenv", "dotenv")
    for path in _test_files():
        for i, line in enumerate(_read(path).splitlines(), 1):
            stripped = line.strip()
            if stripped.startswith("#"):
                continue
            if ".env" not in stripped:
                continue
            if any(p in stripped for p in read_patterns):
                bad.append(f"{path.name}:{i}")
    assert not bad, "测试直接读取了 .env（会造成环境耦合）：\n  " + "\n  ".join(bad)


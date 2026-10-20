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
# 本文件自身含 AST 样例数据，扫描时排除，避免自指
SELF = Path(__file__).name
# 异步函数在 ast 里是 AsyncFunctionDef（与 FunctionDef 平级，不是子类）
FUNC_TYPES = (ast.FunctionDef, ast.AsyncFunctionDef)


def _read(path: Path) -> str:
    """用 utf-8-sig 读取，容忍 BOM（Windows PowerShell 写文件会带 BOM）"""
    return path.read_text(encoding="utf-8-sig")


def _test_files():
    return sorted(p for p in TESTS_DIR.glob("test_*.py") if p.name != SELF)


def _always_truthy(node: ast.AST) -> bool:
    """判断表达式是否"无条件为真"（非空容器 / 非零数 / True / 非空字符串）"""
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
    """函数体内是否有真正的断言（assert 或 pytest.raises/warns 上下文）"""
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


# ---------- 1. 恒真字面量断言 ----------

def test_no_always_truthy_assertions():
    """禁止 assert <非空字面量> 这类永远为真的断言"""
    bad = []
    for path in _test_files():
        tree = ast.parse(_read(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Assert):
                continue
            if _always_truthy(node.test):
                bad.append(f"{path.name}:{node.lineno}")
    assert not bad, "恒真断言（永远通过，等于没断言）：\n  " + "\n  ".join(bad)


# ---------- 2. or 短路恒真 ----------

def test_no_short_circuit_tautology():
    """禁止 `assert <恒真字面量> or <表达式>` —— 右侧永不执行"""
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


# ---------- 3. 自比较 ----------

def test_no_self_comparison():
    """禁止 assert x == x（同一个变量与自身比较，恒真）

    只针对纯引用（Name/Attribute）；`assert f() is f()` 这类用于验证
    单例缓存的断言是有意义的，不在此列。
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


# ---------- 4. 空测试 ----------

def test_no_empty_test_functions():
    """禁止没有任何断言的测试函数（它永远通过）"""
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


# ---------- 5. 空测试文件 ----------

def test_no_empty_test_files():
    """禁止没有测试函数的文件"""
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


# ---------- 6. 测试文件不得依赖本机 .env ----------

def test_tests_do_not_read_env_file_directly():
    """测试不得直接读取 backend/.env（环境耦合会让结果随机器变化）

    只拦截"真的去读文件"的写法；docstring 里解释 .env 语义是允许的。
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


"""卡带合规规则求值 —— 受限表达式求值器(无 eval)。

规则文件 rules/compliance_rules.yaml 的 constraint 是 Python 风格表达式
(action.args.budget_cny <= 500000 or action.args.has_expert_review == true),
此前没有任何求值器(全链路实测 2026-09-29: 卡带 run 只做完整性校验)。
只放行白名单 AST 节点; true/false/null 映射 Python 字面量; 未知属性为 None
(宽松比较, 规则作者负责覆盖缺省)。
"""

from __future__ import annotations

import ast
from typing import Any

_ALLOWED_FUNCS = {"contains", "startswith", "endswith", "len", "abs", "min", "max"}
_ALLOWED_OPS = (ast.And, ast.Or, ast.Not, ast.Eq, ast.NotEq, ast.Lt, ast.LtE, ast.Gt, ast.GtE,
                ast.In, ast.NotIn, ast.Is, ast.IsNot, ast.USub, ast.UAdd)


class _Ctx:
    """action.uri / action.args.* 的只读视图; 缺失属性返回 None。"""

    def __init__(self, data: dict[str, Any]):
        object.__setattr__(self, "_d", data)

    def __getattr__(self, name: str) -> Any:
        d = object.__getattribute__(self, "_d")
        v = d.get(name)
        return _Ctx(v) if isinstance(v, dict) else v


def _func(name: str):
    if name == "contains":
        return lambda a, b: str(b) in str(a)
    if name == "len":
        return len
    if name in ("abs", "min", "max"):
        return {"abs": abs, "min": min, "max": max}[name]
    return lambda s, p: str(s or "").startswith(p) if name == "startswith" else str(s or "").endswith(p)


def _eval(node: ast.expr, ctx: _Ctx) -> Any:
    if isinstance(node, ast.Constant):
        return node.value
    if isinstance(node, ast.Name):
        if node.id == "action":  # 顶层上下文名: action.uri / action.args.* 的根
            return ctx
        if node.id in ("true", "True"):
            return True
        if node.id in ("false", "False"):
            return False
        if node.id in ("null", "None"):
            return None
        return getattr(ctx, node.id, None)
    if isinstance(node, ast.Attribute):
        return getattr(_eval(node.value, ctx), node.attr, None)
    if isinstance(node, ast.BoolOp):
        vals = [_eval(v, ctx) for v in node.values]
        return all(vals) if isinstance(node.op, ast.And) else any(vals)
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.Not, ast.USub, ast.UAdd)):
        v = _eval(node.operand, ctx)
        if isinstance(node.op, ast.Not):
            return not v
        return -v if isinstance(node.op, ast.USub) else +v
    if isinstance(node, ast.Compare):
        left = _eval(node.left, ctx)
        for op, comp in zip(node.ops, node.comparators):
            right = _eval(comp, ctx)
            if isinstance(op, ast.Eq):
                ok = left == right
            elif isinstance(op, ast.NotEq):
                ok = left != right
            elif isinstance(op, (ast.Lt, ast.LtE, ast.Gt, ast.GtE)):
                try:
                    ok = {ast.Lt: left < right, ast.LtE: left <= right, ast.Gt: left > right, ast.GtE: left >= right}[
                        type(op)
                    ]
                except TypeError:
                    return False  # 不可比较(如 None < 5) → 规则不通过 → 按违反处理, 保守
            elif isinstance(op, ast.In):
                ok = left in right
            elif isinstance(op, ast.NotIn):
                ok = left not in right
            else:
                raise ValueError(f"unsupported comparator {type(op).__name__}")
            if not ok:
                return False
            left = right
        return True
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in _ALLOWED_FUNCS:
        return _func(node.func.id)( *[_eval(a, ctx) for a in node.args])
    raise ValueError(f"disallowed expression node: {type(node).__name__}")


def evaluate_constraint(constraint: str, action: dict[str, Any]) -> bool:
    """求值 constraint, action = {"uri": ..., "args": {...}}。任何解析/求值异常 → False(保守阻断)。"""
    try:
        tree = ast.parse(constraint.strip(), mode="eval")
        return bool(_eval(tree.body, _Ctx(action)))
    except Exception:
        return False

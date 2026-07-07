"""Expression evaluation per PROTOCOL.md "Value semantics".

The reference implementation is the prototype's ``coerce``/``fmt``/``interp``/
``evalExpr`` (Flowground.dc.html).  Expressions arrive as JS-flavoured strings;
we rewrite the JS spellings, parse with :mod:`ast` in ``eval`` mode and walk an
explicit whitelist.  Attributes, calls, subscripts, comprehensions, lambdas,
f-strings, walrus — anything not whitelisted — are unreachable by construction:
we never call ``eval``/``exec``/``compile`` on the input, we only interpret the
whitelisted AST nodes ourselves.

Numeric model (PROTOCOL.md "Numeric model: JS float64"): every number is an
IEEE-754 double.  There are NO arbitrary-precision integer paths — literals
become floats immediately, ``**`` is JS ``Math.pow`` (:func:`js_pow`), ``%`` is
``fmod`` (dividend sign), chained comparisons evaluate pairwise left-to-right
with JS bool→number coercion, truthiness is JS's (:func:`js_truthy`: NaN and
``""`` falsy) and number→string follows ECMA ``Number::toString``
(:func:`js_num_str`).
"""

from __future__ import annotations

import ast
import math
import operator
import re
from typing import Any, Dict


class ExprError(Exception):
    """The expression could not be evaluated (catch-all)."""


class EmptyExprError(ExprError):
    """The expression field is empty."""


_NUM_RE = re.compile(r"^-?\d+(\.\d+)?$")
_VAR_RE = re.compile(r"\{(\w+)\}")


# ---------- JS float64 numeric model ----------

_JS_DECIMAL_RE = re.compile(r"[+-]?(\d+(\.\d*)?|\.\d+)([eE][+-]?\d+)?\Z")
_JS_HEX_RE = re.compile(r"0[xX][0-9a-fA-F]+\Z")
_JS_OCT_RE = re.compile(r"0[oO][0-7]+\Z")
_JS_BIN_RE = re.compile(r"0[bB][01]+\Z")


def js_number(v: Any) -> float:
    """JS ``Number(v)`` coercion (PROTOCOL.md): ``''``→0, whitespace trimmed,
    ``0x``/``0o``/``0b`` prefixes parse, ``Infinity``/``+Infinity``/``-Infinity``
    exact-case only, underscores are NOT digit separators, anything else NaN.
    """
    if isinstance(v, bool):
        return 1.0 if v else 0.0
    if isinstance(v, (int, float)):
        try:
            return float(v)
        except OverflowError:  # a beyond-double int is ±Infinity in JS
            return math.inf if v > 0 else -math.inf
    if not isinstance(v, str):
        return math.nan
    s = v.strip()
    if s == "":
        return 0.0
    if s in ("Infinity", "+Infinity"):
        return math.inf
    if s == "-Infinity":
        return -math.inf
    for pattern, base in ((_JS_HEX_RE, 16), (_JS_OCT_RE, 8), (_JS_BIN_RE, 2)):
        if pattern.match(s):
            try:
                return float(int(s[2:], base))
            except OverflowError:
                return math.inf
    if _JS_DECIMAL_RE.match(s):
        # float('1e999') is inf, matching JS; the regex already rejected the
        # Python-isms JS refuses ('1_000', 'inf', 'nan', hex floats, …).
        return float(s)
    return math.nan


def js_truthy(v: Any) -> bool:
    """JS ``Boolean(v)``: NaN, ±0 and ``''`` are falsy.  (Python's ``bool(nan)``
    is True — using it would flip branches.)"""
    if isinstance(v, float):
        return not (v == 0 or math.isnan(v))
    return bool(v)


#: Branch truthiness used by the compiler for iff / loop-while conditions.
truthy = js_truthy


def js_pow(a: float, b: float) -> float:
    """JS ``Math.pow`` on doubles — never Python complex, never big-int.

    Divergences from C/Python ``math.pow`` handled here: NaN**0 is 1,
    (±1)**±Infinity is NaN, negative base with non-integral exponent is NaN,
    0**negative is ±Infinity, overflow is ±Infinity.
    """
    if math.isnan(b):
        return math.nan
    if b == 0:
        return 1.0  # JS: Math.pow(x, ±0) === 1 even for NaN x
    if math.isnan(a):
        return math.nan
    if abs(a) == 1 and math.isinf(b):
        return math.nan  # JS diverges from IEEE pow here
    if a == 0 and b < 0:
        # JS: ±Infinity; -Infinity only for -0 base and odd-integer exponent.
        if math.copysign(1.0, a) < 0 and math.isfinite(b) \
                and b == int(b) and int(b) % 2 != 0:
            return -math.inf
        return math.inf
    if a < 0 and math.isfinite(b) and b != int(b):
        return math.nan
    try:
        return math.pow(a, b)
    except OverflowError:
        if a < 0 and math.isfinite(b) and int(b) % 2 != 0:
            return -math.inf
        return math.inf
    except ValueError:
        return math.nan


def js_fmod(a: float, b: float) -> float:
    """JS ``%``: C ``fmod`` (result takes the dividend's sign); x % 0 and
    Infinity % x are NaN rather than errors."""
    try:
        return math.fmod(a, b)
    except ValueError:
        return math.nan


def js_div(a: float, b: float) -> float:
    """JS ``/``: division by zero yields ±Infinity (NaN for 0/0)."""
    if b == 0:
        if a == 0 or math.isnan(a):
            return math.nan
        sign = math.copysign(1.0, a) * math.copysign(1.0, b)
        return math.inf if sign > 0 else -math.inf
    return a / b


def js_num_str(x: Any) -> str:
    """ECMA ``Number::toString(10)``: plain decimal for 1e-6 ≤ |x| < 1e21,
    JS-spelled exponent form otherwise ('1e-7' not '1e-07', '1e+21'),
    integral values without '.0', String(-0) == '0'."""
    try:
        v = float(x)
    except OverflowError:  # a beyond-double int is ±Infinity in JS
        return "Infinity" if x > 0 else "-Infinity"
    if math.isnan(v):
        return "NaN"
    if math.isinf(v):
        return "Infinity" if v > 0 else "-Infinity"
    if v == 0:
        return "0"
    sign = "-" if v < 0 else ""
    r = repr(abs(v))  # shortest round-trip digits, same digits JS picks
    if "e" in r:
        mant, _, exp = r.partition("e")
        e10 = int(exp)
    else:
        mant, e10 = r, 0
    int_part, _, frac = mant.partition(".")
    digits = (int_part + frac).lstrip("0")
    ip = int_part.lstrip("0")
    if ip:
        n = len(ip) + e10  # value == 0.digits × 10**n
    else:
        n = e10 - (len(frac) - len(frac.lstrip("0")))
    digits = digits.rstrip("0")
    k = len(digits)
    if k <= n <= 21:
        s = digits + "0" * (n - k)
    elif 0 < n <= 21:
        s = digits[:n] + "." + digits[n:]
    elif -6 < n <= 0:
        s = "0." + "0" * (-n) + digits
    else:
        e = n - 1
        s = (digits[0] + ("." + digits[1:] if k > 1 else "")
             + "e" + ("+" if e >= 0 else "-") + str(abs(e)))
    return sign + s


# ---------- prototype value helpers ----------

def coerce(value: Any) -> Any:
    """Ask-block coercion: numeric-looking trimmed strings become numbers
    (always float64 — there is no int type in the JS numeric model)."""
    s = ("" if value is None else str(value)).strip()
    if _NUM_RE.match(s):
        return float(s)
    return s


def fmt(v: Any, bare: bool = False) -> str:
    """Prototype ``fmt``: strings quoted (unless bare), numbers via ECMA
    ``Number::toString``, lowercase booleans."""
    if isinstance(v, str):
        return v if bare else '"' + v + '"'
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        return js_num_str(v)
    return str(v)


def interp(text: Any, variables: Dict[str, Any]) -> str:
    """Replace ``{word}`` with the bare-formatted value when the variable
    exists, else leave the ``{word}`` literally."""

    def _sub(m: "re.Match[str]") -> str:
        key = m.group(1)
        if key in variables:
            return fmt(variables[key], True)
        return m.group(0)

    return _VAR_RE.sub(_sub, "" if text is None else str(text))


_STRING_LITERAL_RE = re.compile(r"(\"(?:[^\"\\]|\\.)*\"|'(?:[^'\\]|\\.)*')")


def _rewrite_code(s: str) -> str:
    s = s.replace("===", "==").replace("!==", "!=")
    s = s.replace("&&", " and ").replace("||", " or ")
    s = re.sub(r"!(?!=)", "not ", s)
    s = re.sub(r"\btrue\b", "True", s)
    s = re.sub(r"\bfalse\b", "False", s)
    return s


def rewrite_js(expr: str) -> str:
    """Rewrite JS spellings to Python:
    ``===``→``==``, ``!==``→``!=``, ``&&``→`` and ``, ``||``→`` or ``,
    ``!x``→``not x`` (not before ``=``), ``true``→``True``, ``false``→``False``.

    String literals are left untouched so ``n + "!"`` keeps its bang (the
    prototype evaluates the raw JS expression, so literals never change).
    """
    parts = _STRING_LITERAL_RE.split(expr)
    return "".join(part if i % 2 else _rewrite_code(part)
                   for i, part in enumerate(parts))


_REL = {
    ast.Lt: operator.lt,
    ast.LtE: operator.le,
    ast.Gt: operator.gt,
    ast.GtE: operator.ge,
}


def _js_equals(left: Any, right: Any) -> bool:
    """``==`` / ``!=`` (loose, since ``===`` collapses to ``==`` on rewrite):
    string-string compares by value, everything else numerically (NaN never
    equals anything)."""
    if isinstance(left, str) and isinstance(right, str):
        return left == right
    a, b = js_number(left), js_number(right)
    if math.isnan(a) or math.isnan(b):
        return False
    return a == b


def _compare_one(op: ast.cmpop, left: Any, right: Any) -> bool:
    if isinstance(op, ast.Eq):
        return _js_equals(left, right)
    if isinstance(op, ast.NotEq):
        return not _js_equals(left, right)
    f = _REL.get(type(op))
    if f is None:
        raise ExprError("comparison not allowed")
    if isinstance(left, str) and isinstance(right, str):
        return bool(f(left, right))
    a, b = js_number(left), js_number(right)
    if math.isnan(a) or math.isnan(b):
        return False  # JS: any relational with NaN is false
    return bool(f(a, b))


def _to_float(v: Any) -> float:
    """Accept only numbers (booleans count, JS-style) for arithmetic — as
    IEEE-754 doubles."""
    if isinstance(v, bool):
        return 1.0 if v else 0.0
    if isinstance(v, (int, float)):
        return float(v)
    raise ExprError("not a number")


def _eval_node(node: ast.AST, variables: Dict[str, Any]) -> Any:
    if isinstance(node, ast.Constant):
        v = node.value
        if isinstance(v, bool):
            return v
        if isinstance(v, str):
            return v
        if isinstance(v, (int, float)) and not isinstance(v, complex):
            try:
                return float(v)  # JS float64: literals are doubles
            except OverflowError:
                return math.inf  # a 400-digit literal is Infinity in JS
        raise ExprError("literal not allowed")

    if isinstance(node, ast.Name):
        if isinstance(node.ctx, ast.Load) and node.id in variables:
            return variables[node.id]
        raise ExprError("unknown variable")

    if isinstance(node, ast.UnaryOp):
        if isinstance(node.op, ast.Not):
            return not js_truthy(_eval_node(node.operand, variables))
        if isinstance(node.op, ast.USub):
            return -_to_float(_eval_node(node.operand, variables))
        raise ExprError("operator not allowed")

    if isinstance(node, ast.BinOp):
        left = _eval_node(node.left, variables)
        right = _eval_node(node.right, variables)
        op = node.op
        if isinstance(op, ast.Add):
            # JS-style: + with a string operand concatenates.
            if isinstance(left, str) or isinstance(right, str):
                return fmt(left, True) + fmt(right, True)
            return _to_float(left) + _to_float(right)
        a, b = _to_float(left), _to_float(right)
        if isinstance(op, ast.Sub):
            return a - b
        if isinstance(op, ast.Mult):
            return a * b
        if isinstance(op, ast.Div):
            return js_div(a, b)
        if isinstance(op, ast.Mod):
            return js_fmod(a, b)
        if isinstance(op, ast.Pow):
            return js_pow(a, b)
        raise ExprError("operator not allowed")

    if isinstance(node, ast.Compare):
        # JS has no chaining: `1 < 2 < 3` is `(1 < 2) < 3` — evaluate pairwise
        # left-to-right, feeding each boolean result into the next comparison.
        left = _eval_node(node.left, variables)
        for op, comparator in zip(node.ops, node.comparators):
            right = _eval_node(comparator, variables)
            left = _compare_one(op, left, right)
        return left

    if isinstance(node, ast.BoolOp):
        result: Any = None
        if isinstance(node.op, ast.And):
            for value in node.values:
                result = _eval_node(value, variables)
                if not js_truthy(result):
                    return result
            return result
        if isinstance(node.op, ast.Or):
            for value in node.values:
                result = _eval_node(value, variables)
                if js_truthy(result):
                    return result
            return result
        raise ExprError("operator not allowed")

    # Everything else — Call, Attribute, Subscript, Lambda, JoinedStr (f-string),
    # NamedExpr (walrus), comprehensions, containers, Starred, Await, ... —
    # is rejected outright.
    raise ExprError("expression not allowed")


def eval_expr(expr: Any, variables: Dict[str, Any]) -> Any:
    """Evaluate a Flowground expression against the current variables.

    Raises :class:`EmptyExprError` for a blank field, :class:`ExprError` for
    any other failure (unknown variable, disallowed syntax, non-finite result).
    """
    source = "" if expr is None else str(expr)
    if not source.strip():
        raise EmptyExprError("this field is empty")
    rewritten = rewrite_js(source)
    try:
        tree = ast.parse(rewritten, mode="eval")
    except (SyntaxError, ValueError, MemoryError, RecursionError):
        raise ExprError("cannot parse") from None
    try:
        result = _eval_node(tree.body, variables)
    except RecursionError:
        raise ExprError("cannot evaluate") from None
    if isinstance(result, float) and not math.isfinite(result):
        raise ExprError("impossible number")
    return result

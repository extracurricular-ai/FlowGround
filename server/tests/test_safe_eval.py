import math
import time

import pytest

from app.safe_eval import (EmptyExprError, ExprError, coerce, eval_expr, fmt,
                           interp, js_num_str, js_number, js_pow, js_truthy)


# ---------- correctness ----------

def test_arithmetic_with_variables():
    assert eval_expr("lap + 1", {"lap": 1}) == 2
    assert eval_expr("lap + 1", {"lap": 3}) == 4


def test_comparisons():
    assert eval_expr("count > 3", {"count": 5}) is True
    assert eval_expr("count > 3", {"count": 1}) is False
    assert eval_expr('name == "Ada"', {"name": "Ada"}) is True
    assert eval_expr('name == "Ada"', {"name": "Bob"}) is False
    assert eval_expr("a <= b", {"a": 2, "b": 2}) is True


def test_true_false_literals():
    assert eval_expr("true", {}) is True
    assert eval_expr("false", {}) is False


def test_js_spelling_rewrites():
    assert eval_expr("a && b", {"a": True, "b": False}) is False
    assert eval_expr("a || b", {"a": False, "b": True}) is True
    assert eval_expr("!ok", {"ok": False}) is True
    assert eval_expr("!ok", {"ok": True}) is False
    assert eval_expr("a === 1", {"a": 1}) is True
    assert eval_expr("a !== 1", {"a": 2}) is True
    assert eval_expr("!done && lap < 4", {"done": False, "lap": 2}) is True


def test_string_number_concat_js_style():
    assert eval_expr('"Lap " + n', {"n": 2}) == "Lap 2"
    assert eval_expr('n + "!"', {"n": 2}) == "2!"
    assert eval_expr('flag + "!"', {"flag": True}) == "true!"
    assert eval_expr('"v" + x', {"x": 2.0}) == "v2"
    assert eval_expr('a + b', {"a": "x", "b": "y"}) == "xy"


def test_string_literals_survive_the_rewrite_pass():
    assert eval_expr('name == "Ada!"', {"name": "Ada!"}) is True
    assert eval_expr('"true" + x', {"x": 1}) == "true1"
    assert eval_expr('s == "a && b"', {"s": "a && b"}) is True


def test_modulo_and_power():
    assert eval_expr("7 % 3", {}) == 1
    assert eval_expr("2 ** 3", {}) == 8
    assert eval_expr("n % 2 == 0", {"n": 4}) is True


def test_unary_minus_and_not():
    assert eval_expr("-x", {"x": 5}) == -5
    assert eval_expr("-2 + 3", {}) == 1
    assert eval_expr("not x", {"x": 0}) is True


def test_boolop_returns_operand_values():
    # JS/Python parity: && / || return operand values, not booleans.
    assert eval_expr("a || b", {"a": 0, "b": 7}) == 7
    assert eval_expr("a && b", {"a": 1, "b": 7}) == 7


# ---------- formatting ----------

def test_fmt_numbers_js_style():
    assert fmt(2.0) == "2"
    assert fmt(2) == "2"
    assert fmt(-3) == "-3"
    assert fmt(1.5) == "1.5"
    assert fmt(0) == "0"


def test_fmt_strings_and_bools():
    assert fmt("x") == '"x"'
    assert fmt("x", True) == "x"
    assert fmt(True) == "true"
    assert fmt(False) == "false"


def test_coerce():
    assert coerce("12") == 12
    # JS float64 numeric model: every number is a double, never a Python int.
    assert isinstance(coerce("12"), float)
    assert coerce(" -3.5 ") == -3.5
    assert coerce("Ada") == "Ada"
    assert coerce("") == ""
    assert coerce("1.2.3") == "1.2.3"
    assert coerce(None) == ""


def test_interp_substitution():
    assert interp("Hello, {name}!", {"name": "Ada"}) == "Hello, Ada!"
    assert interp("Lap {lap}", {"lap": 1}) == "Lap 1"
    assert interp("{ok}", {"ok": True}) == "true"
    assert interp("{a}{b}", {"a": 1, "b": 2}) == "12"


def test_interp_missing_var_left_literal():
    assert interp("Lap {lap}", {}) == "Lap {lap}"
    assert interp("Hi {name}, lap {lap}", {"name": "Ada"}) == "Hi Ada, lap {lap}"


# ---------- safety ----------

@pytest.mark.parametrize("expr", [
    '__import__("os").system("id")',
    '__import__("os")',
    'open("/etc/passwd")',
    "x.__class__",
    "().__class__.__bases__",
    "x.__class__.__mro__",
    "[1, 2][0]",
    '"abc"[0]',
    "x[0]",
    "lambda: 1",
    "(y := 2)",
    'f"{1 + 1}"',
    'f"{().__class__}"',
    "[1, 2]",
    "{1: 2}",
    "(1, 2)",
    "{1, 2}",
    "print(1)",
    "getattr(x, 'y')",
    "x if True else 0",
    "[i for i in range(3)]",
    "1; 2",
    "import os",
    "x = 1",
])
def test_dangerous_or_disallowed_rejected(expr):
    with pytest.raises(ExprError):
        eval_expr(expr, {"x": 1})


def test_unknown_variable_rejected():
    with pytest.raises(ExprError):
        eval_expr("nope + 1", {})
    with pytest.raises(ExprError):
        eval_expr("nope", {"other": 1})


def test_empty_expr_rejected():
    with pytest.raises(EmptyExprError):
        eval_expr("", {})
    with pytest.raises(EmptyExprError):
        eval_expr("   ", {})
    with pytest.raises(EmptyExprError):
        eval_expr(None, {})


def test_non_finite_results_rejected():
    with pytest.raises(ExprError):
        eval_expr("1 / 0", {})
    with pytest.raises(ExprError):
        eval_expr("1e308 * 10", {})
    with pytest.raises(ExprError):
        eval_expr("2 ** 100000", {})


# ---------- JS float64 numeric model ----------
# Every JS-side expectation below was checked against `node -e`.

def test_js_pow_negative_base_fractional_exponent_is_nan_not_complex():
    r = js_pow(-8.0, 0.5)
    assert isinstance(r, float) and math.isnan(r)
    # through the evaluator: NaN final result → eval error, never complex
    with pytest.raises(ExprError):
        eval_expr("(-8) ** 0.5", {})
    with pytest.raises(ExprError):
        eval_expr("x ** 0.5", {"x": -8.0})


def test_js_pow_edge_cases_match_math_pow_js():
    assert js_pow(float("nan"), 0.0) == 1.0          # Math.pow(NaN, 0) === 1
    assert math.isnan(js_pow(2.0, float("nan")))
    assert math.isnan(js_pow(1.0, math.inf))         # JS diverges from IEEE
    assert math.isnan(js_pow(-1.0, math.inf))
    assert js_pow(0.0, -1.0) == math.inf
    assert js_pow(-0.0, -1.0) == -math.inf
    assert js_pow(-0.0, -2.0) == math.inf
    assert js_pow(-2.0, 3.0) == -8.0
    assert js_pow(2.0, 100000.0) == math.inf         # overflow → Infinity
    assert js_pow(-2.0, 100001.0) == -math.inf       # odd exponent keeps sign
    assert js_pow(2.0, -math.inf) == 0.0


def test_pow_guard_removed_2_to_300_computes():
    # JS computes 2**300 fine; the old abs(b)>256 guard wrongly rejected it.
    assert eval_expr("2 ** 300", {}) == 2.037035976334486e+90


def test_huge_power_is_fast_eval_error_not_oom():
    # 9**9**9 as Python ints tried to build a 369-million-digit number (OOM);
    # as float64 it overflows to Infinity instantly → eval error.
    start = time.monotonic()
    with pytest.raises(ExprError):
        eval_expr("9 ** 9 ** 9", {})
    assert time.monotonic() - start < 1.0


def test_modulo_takes_dividend_sign_like_js():
    # node: 5%3=2, -5%3=-2, 5%-3=2, -5%-3=-2, 5.5%2=1.5  (Python: -5%3 == 1)
    assert eval_expr("5 % 3", {}) == 2
    assert eval_expr("-5 % 3", {}) == -2
    assert eval_expr("5 % -3", {}) == 2
    assert eval_expr("-5 % -3", {}) == -2
    assert eval_expr("5.5 % 2", {}) == 1.5


def test_modulo_by_zero_is_nan_mid_expression():
    # node: (1%0)==(1%0) → NaN==NaN → false; a bare 1%0 is a non-finite result
    assert eval_expr("(1 % 0) == (1 % 0)", {}) is False
    with pytest.raises(ExprError):
        eval_expr("1 % 0", {})


def test_division_by_zero_is_infinity_mid_expression():
    # node: (1/0) > 0 → Infinity > 0 → true (Python raises ZeroDivisionError)
    assert eval_expr("(1 / 0) > 0", {}) is True
    assert eval_expr("(0 / 0) == (0 / 0)", {}) is False


def test_chained_comparisons_are_pairwise_left_to_right():
    # node: 1<2<3 → true ((1<2)<3 → true<3 → 1<3); 3>2>1 → false (true>1)
    assert eval_expr("1 < 2 < 3", {}) is True
    assert eval_expr("3 > 2 > 1", {}) is False
    # Python chaining would say True for both — that is the bug being killed.


def test_js_truthy_nan_zero_empty_string_falsy():
    assert js_truthy(float("nan")) is False
    assert js_truthy(0.0) is False
    assert js_truthy(-0.0) is False
    assert js_truthy("") is False
    assert js_truthy("0") is True      # non-empty string is truthy in JS
    assert js_truthy(math.inf) is True
    assert js_truthy(1.0) is True


def test_nan_through_not_and_or_in_evaluator():
    nan = float("nan")
    # node: !NaN → true  (Python's bool(nan) is True — would flip this)
    assert eval_expr("not x", {"x": nan}) is True
    assert eval_expr("!x", {"x": nan}) is True
    assert eval_expr("x || 5", {"x": nan}) == 5
    assert eval_expr("x > 0", {"x": nan}) is False
    assert eval_expr("x < 0", {"x": nan}) is False
    assert eval_expr("x == x", {"x": nan}) is False


def test_number_to_string_matches_node():
    # every expectation below is String(x) output from node
    assert js_num_str(0.1 + 0.2) == "0.30000000000000004"
    assert js_num_str(1e21) == "1e+21"
    assert js_num_str(1e-7) == "1e-7"
    assert js_num_str(123456789012345680000.0) == "123456789012345680000"
    assert js_num_str(5e-324) == "5e-324"
    assert js_num_str(-0.0) == "0"
    assert js_num_str(1e-6) == "0.000001"
    assert js_num_str(1.5e-7) == "1.5e-7"
    assert js_num_str(2.0 ** 300) == "2.037035976334486e+90"
    assert js_num_str(100.0) == "100"
    assert js_num_str(1234.5) == "1234.5"
    assert js_num_str(-1234.5) == "-1234.5"
    assert js_num_str(float("nan")) == "NaN"
    assert js_num_str(math.inf) == "Infinity"
    assert js_num_str(-math.inf) == "-Infinity"
    assert js_num_str(10 ** 400) == "Infinity"   # beyond-double int, no crash
    assert fmt(1e21) == "1e+21"                    # fmt goes through the same
    assert interp("x is {x}", {"x": 1e-7}) == "x is 1e-7"
    assert eval_expr('"n=" + x', {"x": 1e21}) == "n=1e+21"


@pytest.mark.parametrize("raw,expected", [
    ("", 0.0),
    ("   ", 0.0),
    (" 12 ", 12.0),
    ("0x10", 16.0),
    ("0X10", 16.0),
    ("0o17", 15.0),
    ("0b101", 5.0),
    ("Infinity", math.inf),
    ("+Infinity", math.inf),
    ("-Infinity", -math.inf),
    (".5", 0.5),
    ("5.", 5.0),
    ("1e3", 1000.0),
    ("+12", 12.0),
    ("-12.5e-1", -1.25),
    ("1e999", math.inf),
    (True, 1.0),
    (False, 0.0),
    (3.5, 3.5),
    (10 ** 400, math.inf),      # beyond-double int is Infinity, not a crash
    (-(10 ** 400), -math.inf),
])
def test_js_number_coercion_table(raw, expected):
    assert js_number(raw) == expected


@pytest.mark.parametrize("raw", [
    "infinity", "INFINITY", "inf",     # exact-case 'Infinity' only
    "1_000", "0x1_0",                  # underscores are not digit separators
    "12px", "nan", "0x", "- 12", "1e", "0xg", None, {"a": 1},
])
def test_js_number_rejects_to_nan(raw):
    assert math.isnan(js_number(raw))

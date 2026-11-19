from decimal import Decimal, ROUND_HALF_UP


def D(x):
    return None if x is None else Decimal(str(x))


def q(x) -> Decimal:
    x = x if isinstance(x, Decimal) else Decimal(str(x))
    return x.quantize(Decimal("0.01"), ROUND_HALF_UP)


def f(x):
    return None if x is None else float(q(Decimal(x)))

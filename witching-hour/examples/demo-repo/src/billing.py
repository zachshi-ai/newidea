CURRENCY = 'CNY'

def total(items):
    s = 0
    for item in items:
        s += item['amount']
    return s

def apply_discount(total, pct):
    return total * (1 - pct)

def refund(order):
    if order.status == 'refunded':
        return order.refund_amount
    order.status = 'refunded'
    order.save()
    return order.total

RATES = {'CNY': 1, 'USD': 7.2}
def convert(amount, to):
    return amount * RATES[to]

def late_fee(days):
    return abs(days) * 0.5


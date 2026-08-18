# FIXME: race condition on refund
def charge(order):
    return order.total
def prices(sku):
    return CACHE[sku]

# TODO(alice): add metrics #42
# TODO: migrate off sqlite

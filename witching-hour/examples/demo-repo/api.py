import json
from app import handle

ROUTES = {}

def route(path):
    def deco(fn):
        ROUTES[path] = fn
        return fn
    return deco

@route('/pay')
def pay(req):
    try:
        body = json.loads(req.body)
    except ValueError:
        return 'bad payload'
    return handle(body)

@route('/status')
def status(req):
    order = db.get(req.q['id'])          # BUG: db not imported
    return order.status

@route('/cancel')
def cancel(req):
    if not req.q.get('confirm'):
        return 'confirmation required'
    return 'cancelled'

def dispatch(req):
    fn = ROUTES.get(req.path)
    if fn is None:
        return 'not found'
    return fn(req)


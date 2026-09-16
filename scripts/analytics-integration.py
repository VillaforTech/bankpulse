"""Exercise the real Social Split producer and query the independent projection."""
import json
import subprocess
import time
import urllib.request
from pathlib import Path


def api(path, payload=None):
    req = urllib.request.Request('http://localhost:8080/api/splits' + path,
        data=None if payload is None else json.dumps(payload).encode(),
        headers={'Content-Type': 'application/json'})
    with urllib.request.urlopen(req, timeout=10) as response:
        return json.load(response)


def snapshot():
    command = ['docker', 'compose', '-f', 'compose.yaml', '-f', 'compose.analytics.yaml',
        'exec', '-T', 'business-analytics', 'python', '-c',
        "import urllib.request; print(urllib.request.urlopen('http://localhost:8000/snapshot').read().decode())"]
    return json.loads(subprocess.check_output(command, text=True))


before = snapshot()
session = api('', {'hostMemberId': 'integration', 'totalAmount': 100, 'currency': 'USD'})
sid = session['id']
for member, amount in [('one', 60), ('two', 40)]:
    session = api('/' + sid + '/participants', {'memberId': member, 'shareAmount': amount})
for participant in session['participants']:
    api('/' + sid + '/participants/' + participant['id'] + '/authorize', {'paymentReference': 'integration-demo'})
closed = api('/' + sid + '/close', {})
assert closed['status'] == 'COMPLETED', closed
for _ in range(60):
    result = snapshot()
    if result.get('valid') and result['kpis']['B-K1'].get('sample', 0) > before['kpis']['B-K1'].get('sample', 0):
        break
    time.sleep(.5)
else:
    raise AssertionError(result)
assert float(result['kpis']['B-K1']['value']) == 100, result
assert float(result['kpis']['B-K2']['value'].get('USD', 0)) == 0, result
Path('artifacts').mkdir(exist_ok=True)
Path('artifacts/analytics-integration.json').write_text(json.dumps({'sessionId': sid, 'closed': closed, 'snapshot': result}, indent=2))
print('Real producer to analytics passed:', sid, 'revision', result['revision'])

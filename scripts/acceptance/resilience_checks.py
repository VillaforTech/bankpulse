#!/usr/bin/env python3
"""Destructive service tests for a disposable local/CI Compose deployment only.

Never point this harness at a production or shared running deployment.
Component fixtures use their own uniquely named Compose project and volume.
"""
import argparse
import json
import os
import subprocess
import time
import uuid
from pathlib import Path
from business_test_social_split import _http

OUT = Path('artifacts/acceptance')
STACK = ['docker', 'compose', '-f', 'compose.yaml', '-f', 'compose.analytics.yaml']


def run(command, **kwargs):
    return subprocess.run(command, check=True, text=True, timeout=240, **kwargs)


def snapshot():
    code = "import urllib.request; print(urllib.request.urlopen('http://localhost:8000/snapshot').read().decode())"
    return json.loads(run(STACK + ['exec', '-T', 'business-analytics', 'python', '-c', code], capture_output=True).stdout)


def until(predicate, timeout=75):
    deadline = time.monotonic() + timeout
    last = None
    while time.monotonic() < deadline:
        try:
            last = snapshot()
        except subprocess.CalledProcessError:
            time.sleep(.2)
            continue
        if predicate(last):
            return last
        time.sleep(.2)
    raise AssertionError(last)


def sql(query):
    return run(STACK + ['exec', '-T', 'postgres', 'sh', '-c',
        'exec psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Atc "$1"', 'sh', query], capture_output=True).stdout.strip()


def main(base):
    OUT.mkdir(parents=True, exist_ok=True)
    report = {'scope': 'disposable platform outage and isolated component fixtures', 'checks': []}
    def record(name, **data):
        report['checks'].append({'name': name, 'result': 'PASS', **data})
        (OUT/'resilience.json').write_text(json.dumps(report, indent=2)+'\n')
        print(name, 'PASS', flush=True)
    before = until(lambda s: s['valid'])
    old_count = before['kpis']['counts']['sessions']
    marker = str(uuid.uuid4())
    sid = None
    try:
        run(STACK + ['stop', 'redpanda'])
        status, session = _http('POST', base+'/api/splits', {'hostMemberId':marker,'totalAmount':100,'currency':'USD'})
        assert status == 201, (status, session)
        sid = session['id']
        assert str(uuid.UUID(sid)) == sid
        assert sql(f"select count(*) from social_split.social_split_outbox_events where aggregate_id='{sid}' and not published") == '1'
        degraded = until(lambda s: not s['valid'])
        record('broker down: API commits with durable pending outbox and analytics not fresh', sessionId=sid, quality=degraded['quality'])
    finally:
        run(STACK + ['start', 'redpanda'])
    restored = until(lambda s: s['valid'] and s['kpis']['counts']['sessions'] == old_count+1)
    deadline = time.monotonic()+30
    while sql(f"select count(*) from social_split.social_split_outbox_events where aggregate_id='{sid}' and not published") != '0':
        assert time.monotonic()<deadline, 'outbox did not drain'
        time.sleep(.2)
    record('broker recovery drains outbox without loss', sessions=restored['kpis']['counts']['sessions'])
    try:
        run(STACK + ['kill', '-s', 'SIGKILL', 'business-analytics'])
        status, queued = _http('POST',base+'/api/splits',{'hostMemberId':str(uuid.uuid4()),'totalAmount':100,'currency':'USD'})
        assert status == 201
    finally:
        run(STACK + ['start', 'business-analytics'])
    recovered = until(lambda s: s['valid'] and s['kpis']['counts']['sessions'] == old_count+2)
    assert recovered['kpis']['B-K1'] == restored['kpis']['B-K1']
    record('consumer SIGKILL recovery preserves projection and catches up', sessions=recovered['kpis']['counts']['sessions'])

    # Isolated real Kafka fixtures cover duplicates, reordering and timer expiry.
    project = 'bankpulse-acceptance-'+uuid.uuid4().hex[:10]
    command = ['docker','compose','-p',project,'-f','services/business-analytics/compose.test.yaml']
    env = {**os.environ, 'ANALYTICS_TEST_PORT':'0'}
    try:
        run(command+['up','-d','--build','--wait'], env=env)
        port = run(command+['port','analytics','8000'],env=env,capture_output=True).stdout.strip().rsplit(':',1)[1]
        run(['python3','services/business-analytics/tests/integration.py','--project',project,'--url','http://127.0.0.1:'+port,'--output',str(OUT/'component-resilience.json')],env=env)
        record('real broker duplicate, ordering, restart and accelerated timer fixtures', evidence='component-resilience.json', timerSeconds=3, productionTimerSeconds=120)
    finally:
        with (OUT/'component-runtime.log').open('w') as log:
            subprocess.run(command+['logs','--no-color','--tail=100'],stdout=log,stderr=subprocess.STDOUT,env=env,timeout=30)
        # This unique test project and its volume were created by this invocation.
        run(command+['down','-v'],env=env)


if __name__ == '__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base-url',default='http://localhost:8080')
    args=parser.parse_args()
    main(args.base_url)

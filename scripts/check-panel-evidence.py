#!/usr/bin/env python3
"""Fail closed on API-only, missing, lossy or incoherent panel measurements."""
import json, math, sys

def verify(d):
    assert d.get('measurementTarget') == 'grafana-render', 'Actual panel measurement is required'
    assert not d.get('coberturaParcial') and not d.get('coberturaParcialPanelPendiente'), 'Partial API coverage does not pass'
    samples=d['samples']
    assert d['requested'] == d['observed'] == len(samples) == 100
    assert d['lost'] == 0 and not d['errors']
    assert len({s['correlationId'] for s in samples}) == 100
    assert len({s['eventId'] for s in samples}) == 100
    values=[]
    for s in samples:
        assert s['correlationId'] and s['rendered'] is True and s['correct'] is True
        assert s['quality']=='FRESH' and s['revision']>0
        value=float(s['latencyMs']);assert math.isfinite(value) and value>=0
        panels=s['panels']
        for name in ('integrity','gap','stale'):
            assert panels[name]['quality']=='ACTUAL' and panels[name]['eventId']==s['eventId']
        assert float(panels['integrity']['value'])==100
        assert float(panels['gap']['value'])==0
        assert round(float(panels['stale']['value'])*100)==panels['expectedStaleCents']
        values.append(value)
    p95=sorted(values)[94]
    assert p95<=1000 and abs(d['p95Ms']-p95)<0.001
if __name__=='__main__':
    with open(sys.argv[1]) as f:verify(json.load(f))
    print('100 correct, fresh, correlated Grafana renders passed')

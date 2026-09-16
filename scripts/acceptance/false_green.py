#!/usr/bin/env python3
"""Prove that the unchanged business test detects a real temporary mutant.

Disposable Compose only. Builds a separate image from a temporary source copy,
restores the original image in finally, and retains all historical test data.
This proves mutation detection, not a GitHub PR review/branch-protection decision.
"""
import difflib
import json
import shutil
import subprocess
import tempfile
import uuid
from pathlib import Path
from business_test_social_split import esperar_readiness, _http
from resilience_checks import snapshot, until

OUT=Path('artifacts/acceptance/false-green')
BASE=['docker','compose','-f','compose.yaml']
TEST=['python3','scripts/acceptance/business_test_social_split.py']
SOURCE=Path('services/social-split-api')
JAVA=Path('src/main/java/com/bankpulse/split/SplitSession.java')


def execute(args, **kw):
    return subprocess.run(args,check=True,text=True,timeout=300,**kw)


def business(name, expected):
    result=subprocess.run(TEST,text=True,capture_output=True,timeout=120)
    (OUT/(name+'.log')).write_text(result.stdout+result.stderr)
    assert result.returncode==expected, (name,result.returncode,result.stdout,result.stderr)
    if expected==1:
        assert 'FALSO VERDE DETECTADO' in result.stdout
        assert 'caso_falso_verde_60_30_de_100=FAIL' in result.stdout
        for name in ['caso_sano_60_40_de_100','caso_sin_consentimiento','caso_cierre_repetido']:
            assert name+'=PASS' in result.stdout
    return result.returncode


def main():
    OUT.mkdir(parents=True,exist_ok=True)
    evidence={'scope':'temporary real service mutation; unchanged business test; original data retained'}
    evidence['baseExit']=business('base',0)
    tag='bankpulse-acceptance-mutant:'+uuid.uuid4().hex
    with tempfile.TemporaryDirectory(prefix='bankpulse-mutant-') as temporary:
        copy=Path(temporary)/'service'
        shutil.copytree(SOURCE,copy,ignore=shutil.ignore_patterns('target'))
        original=(copy/JAVA).read_text()
        guard='    if(shares.compareTo(totalAmount)!=0) throw new DomainViolationException("participant shares must equal total amount");\n'
        assert original.count(guard)==1, 'mutation no longer matches source'
        mutated=original.replace(guard,'')
        (copy/JAVA).write_text(mutated)
        (OUT/'mutation.diff').write_text(''.join(difflib.unified_diff(original.splitlines(True),mutated.splitlines(True),fromfile=str(SOURCE/JAVA),tofile=str(SOURCE/JAVA))))
        override=Path(temporary)/'override.json'
        override.write_text(json.dumps({'services':{'social-split-api':{'image':tag}}}))
        try:
            execute(['docker','build','-t',tag,str(copy)])
            execute(BASE+['-f',str(override),'up','-d','--no-deps','--no-build','--wait','social-split-api'])
            execute(BASE+['restart','console'])
            esperar_readiness('http://localhost:8080')
            health_status, evidence['healthBefore']=_http('GET','http://localhost:8080/health/social-split')
            assert health_status==200
            evidence['mutantExit']=business('mutant',1)
            health_status, evidence['healthAfter']=_http('GET','http://localhost:8080/health/social-split')
            assert health_status==200
            assert evidence['healthBefore']['status']==evidence['healthAfter']['status']=='UP'
            observed=until(lambda s:s['valid'] and s['kpis']['B-K1']['value']<100 and float(s['kpis']['B-K2']['value'].get('USD',0))>=10)
            evidence['violatedProjection']=observed
            execute(['node','scripts/acceptance/breach-panel.cjs'])
        finally:
            execute(BASE+['up','-d','--no-deps','--no-build','--force-recreate','--wait','social-split-api'])
            execute(BASE+['restart','console'])
            subprocess.run(['docker','image','rm',tag],check=False,timeout=30)
        esperar_readiness('http://localhost:8080')
        evidence['correctedExit']=business('corrected',0)
        final=until(lambda s:s['valid'] and float(s['kpis']['B-K2']['value'].get('USD',0))>=10)
        evidence['historicalBreachRetained']=final['kpis']
        (OUT/'result.json').write_text(json.dumps(evidence,indent=2)+'\n')
        print('PASS: real mutant rejected, health UP, original image restored, history retained')


if __name__=='__main__':
    main()

import importlib.util
import json
from pathlib import Path
import unittest
spec=importlib.util.spec_from_file_location('gate',Path('scripts/check-panel-evidence.py'))
gate=importlib.util.module_from_spec(spec);spec.loader.exec_module(gate)
class PanelGateTests(unittest.TestCase):
    def fixture(self):
        return {'measurementTarget':'grafana-render','requested':100,'observed':100,'lost':0,'errors':[], 'p95Ms':100, 'samples':[{'correlationId':str(i),'eventId':str(i),'panels':{'integrity':{'quality':'ACTUAL','eventId':str(i),'value':'100'},'gap':{'quality':'ACTUAL','eventId':str(i),'value':'0'},'stale':{'quality':'ACTUAL','eventId':str(i),'value':'60'},'expectedStaleCents':6000},'rendered':True,'correct':True,'quality':'FRESH','revision':i+1,'latencyMs':100} for i in range(100)]}
    def test_complete_evidence_passes(self):gate.verify(self.fixture())
    def test_partial_missing_and_loss_block(self):
        for change in [{'measurementTarget':'api'},{'coberturaParcialPanelPendiente':True},{'lost':1},{'observed':99},{'p95Ms':10}]:
            d=self.fixture();d.update(change)
            with self.assertRaises(AssertionError):gate.verify(d)
    def test_bad_samples_block(self):
        for change in [{'latencyMs':float('nan')},{'quality':'STALE'},{'correct':False},{'correlationId':'1'}]:
            d=self.fixture();d['samples'][0].update(change)
            with self.assertRaises(AssertionError):gate.verify(d)

    def test_incorrect_or_uncorrelated_panel_blocks(self):
        for name,field,value in [('gap','value','10'),('stale','value','50'),('integrity','value','99'),('stale','quality','DESACTUALIZADO'),('gap','eventId','other')]:
            with self.subTest(panel=name,field=field):
                d=self.fixture()
                d['samples'][0]['panels'][name][field]=value
                with self.assertRaises(AssertionError):gate.verify(d)

class ProvisionedBusinessPanelTests(unittest.TestCase):
    def setUp(self):
        self.path = Path('observability/grafana/dashboards/bankpulse-deber-01-business.json')
        self.dashboard = json.loads(self.path.read_text())

    def test_dashboard_uses_grafana_live_without_auto_refresh(self):
        self.assertEqual(self.dashboard['refresh'], '')
        self.assertEqual(self.dashboard['uid'], 'bankpulse-deber-01')
        targets = [target for panel in self.dashboard['panels'] if panel.get('type') == 'bankpulse-business-panel' for target in panel.get('targets', [])]
        self.assertTrue(targets)
        self.assertTrue(all(target['channel'] == 'stream/bankpulse/business' for target in targets))

    def test_dashboard_contains_three_business_indicators(self):
        fields = {panel.get('options', {}).get('field') for panel in self.dashboard['panels']}
        self.assertTrue({'integrity_percent', 'closure_gap', 'stale_authorized'} <= fields)

    def test_technical_health_and_history_use_prometheus(self):
        prometheus = [panel for panel in self.dashboard['panels'] if panel.get('datasource', {}).get('type') == 'prometheus']
        self.assertEqual(len(prometheus), 2)
        expressions = {target['expr'] for panel in prometheus for target in panel['targets']}
        self.assertIn('up{job="business-analytics"}', expressions)
        self.assertIn('bankpulse_analytics_revision', expressions)

    def test_panel_expires_stale_data_and_exposes_correlation(self):
        source = Path('observability/grafana/plugins/bankpulse-business-panel/module.js').read_text()
        self.assertIn("now - lastArrival.current > 3000", source)
        self.assertIn("data-correlation-id", source)
        self.assertIn("revision >= Number(latest.current.revision)", source)

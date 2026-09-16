"""The acceptance oracle must never interpret server failure as business rejection."""
import importlib.util
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

spec=importlib.util.spec_from_file_location('business_acceptance', Path('scripts/acceptance/business_test_social_split.py'))
business=importlib.util.module_from_spec(spec)
sys.modules[spec.name]=business
spec.loader.exec_module(business)

class RejectionTests(unittest.TestCase):
    def test_http_500_is_not_a_business_rejection(self):
        session={'id':'s','status':'OPEN','totalAmount':100,'participants':[{'id':'a'},{'id':'b'}]}
        for scenario in [business.escenario_falso_verde,business.escenario_sin_consentimiento]:
            with self.subTest(scenario=scenario.__name__), \
                 patch.object(business,'_crear_split',return_value=session), \
                 patch.object(business,'_agregar_participante',return_value=session), \
                 patch.object(business,'_autorizar',return_value=(200,{})), \
                 patch.object(business,'_cerrar',return_value=(500,{})), \
                 patch.object(business,'_obtener',return_value=session):
                result=business.ResumenNegocio()
                scenario('http://unused',result)
                self.assertFalse(result.todo_ok)

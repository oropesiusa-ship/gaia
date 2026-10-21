"""Fixed post-promotion matrix, with the historical administrative exclusions."""
import json
from pathlib import Path
import sys
import unittest

MODULES=('test_cpu_sandbox','test_provenance','test_manifest','test_ledger','test_gates','test_publication','test_rollback','test_certification','test_autonomous_mvp',
         'test_observation','test_diagnosis','test_prioritization','test_learning','test_meta_strategy','test_external_research','test_local_intelligence','test_cognition','test_autonomy')
EXCLUDED={'test_certification.RealCertificationTests.test_real_unmocked_cli_certifies_pipeline_only_and_preserves_normal_state':'No separate new Prueba A during closed-loop post-promotion verification.'}


def flatten(suite):
    for item in suite:
        if isinstance(item,unittest.TestSuite):yield from flatten(item)
        else:yield item


def main():
    sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'tests'))
    suite=unittest.defaultTestLoader.loadTestsFromNames(MODULES)
    for test in flatten(suite):
        if test.id()in EXCLUDED:
            method=getattr(type(test),test._testMethodName);method.__unittest_skip__=True;method.__unittest_skip_why__=EXCLUDED[test.id()]
    result=unittest.TextTestRunner(verbosity=1).run(suite)
    print(json.dumps({'tests':result.testsRun,'skips':len(result.skipped),'failures':len(result.failures),'errors':len(result.errors),'status':'PASS'if result.wasSuccessful()else'FAIL'}))
    return 0 if result.wasSuccessful()else 1


if __name__=='__main__':raise SystemExit(main())

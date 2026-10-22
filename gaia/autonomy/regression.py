"""Fixed post-promotion matrix, with the historical administrative exclusions."""
import argparse
import json
from pathlib import Path
import re
import sys
import unittest

MODULES=('test_cpu_sandbox','test_provenance','test_manifest','test_ledger','test_gates','test_publication','test_rollback','test_certification','test_autonomous_mvp',
         'test_observation','test_diagnosis','test_prioritization','test_learning','test_meta_strategy','test_external_research','test_local_intelligence','test_cognition','test_autonomy')
EXCLUDED={'test_certification.RealCertificationTests.test_real_unmocked_cli_certifies_pipeline_only_and_preserves_normal_state':'No separate new Prueba A during closed-loop post-promotion verification.'}


def flatten(suite):
    for item in suite:
        if isinstance(item,unittest.TestSuite):yield from flatten(item)
        else:yield item


def rerun_id(test):
    """A name loadTestsFromNames can load again: the parent test of a subTest, the class or module of a fixture error."""
    if isinstance(test,unittest.case._SubTest):return test.test_case.id()
    if isinstance(test,unittest.suite._ErrorHolder):
        match=re.fullmatch(r'\w+ \(([\w.]+)\)',test.description)
        return match.group(1)if match else None
    return test.id()


def main(argv=None):
    """Run the fixed matrix, or only the given test IDs (the single re-run of failed tests), and report each failing test."""
    ap=argparse.ArgumentParser();ap.add_argument('--only',nargs='+');ap.add_argument('--report')
    args=ap.parse_args(argv)
    sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'tests'))
    suite=unittest.defaultTestLoader.loadTestsFromNames(args.only or MODULES)
    for test in flatten(suite):
        if test.id()in EXCLUDED:
            method=getattr(type(test),test._testMethodName);method.__unittest_skip__=True;method.__unittest_skip_why__=EXCLUDED[test.id()]
    result=unittest.TextTestRunner(verbosity=1).run(suite)
    failed=[{'id':test.id(),'rerun_id':rerun_id(test),'kind':kind,'traceback':trace}for kind,rows in (('FAILURE',result.failures),('ERROR',result.errors))for test,trace in rows]
    failed+=[{'id':test.id(),'rerun_id':rerun_id(test),'kind':'UNEXPECTED_SUCCESS','traceback':''}for test in result.unexpectedSuccesses]
    summary={'tests':result.testsRun,'skips':len(result.skipped),'failures':len(result.failures),'errors':len(result.errors),
             'unexpected_successes':len(result.unexpectedSuccesses),'status':'PASS'if result.wasSuccessful()else'FAIL'}
    if args.report:Path(args.report).write_text(json.dumps({**summary,'scope':'ONLY_GIVEN_TEST_IDS'if args.only else'FIXED_MATRIX','failed':failed}))
    print(json.dumps(summary))
    return 0 if result.wasSuccessful()else 1


if __name__=='__main__':raise SystemExit(main())

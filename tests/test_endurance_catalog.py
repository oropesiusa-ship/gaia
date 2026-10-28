"""1.1 §7: catalog of verified references across lineages; reuse only on an exact binding."""
import copy
import unittest

from gaia.autonomy.catalog import catalog,references,applicability,BINDING
from test_autonomy_integration import Fixture,FakeV2


class Promoting(FakeV2):decisions=('accepted',);promote=True;verification='PASS'


class CatalogTests(Fixture):
    def test_promotions_are_verified_references_with_their_binding(self):
        a=self.lineage()['lineage_id'];self.go(self.loop(a,factory=Promoting,promotion=True))
        b=self.lineage()['lineage_id'];self.go(self.loop(b))
        value=catalog(self.state)
        self.assertEqual({x['lineage_id']:x['verified_references']>0 for x in value['lineages']},{a:True,b:False})
        ref=value['references'][0];self.assertEqual(ref['kind'],'PROMOTED_VERSION');self.assertEqual(set(ref['binding']),set(BINDING))
        self.assertEqual(value['scope'],'INDEX_ONLY_NO_STORE_MERGE_EXACT_BINDING_REUSE')
    def test_reuse_is_exact_or_incompatible_never_equivalent(self):
        a=self.lineage()['lineage_id'];self.go(self.loop(a,factory=Promoting,promotion=True))
        ref=references(self.state,a)[0];self.assertEqual(applicability(ref,ref['binding'])['status'],'UNASSESSED')  # unit evidence has no environment hash
        ref['binding']['environment_hash']='a'*64;binding=copy.deepcopy(ref['binding'])
        self.assertEqual(applicability(ref,binding),{'status':'EXACT','differing':[]})
        other={**binding,'environment_hash':'f'*64}
        self.assertEqual(applicability(ref,other),{'status':'INCOMPATIBLE','differing':['environment_hash']})
        self.assertEqual(applicability(ref,{**binding,'source_identity_hash':None})['status'],'UNASSESSED')
    def test_reverted_or_unverified_promotions_are_not_references(self):
        class Reverted(Promoting):verification='FAIL'
        a=self.lineage()['lineage_id'];r=self.go(self.loop(a,factory=Reverted,promotion=True))
        self.assertEqual(r['stopping_reason'],'POST_PROMOTION_REGRESSION_ROLLED_BACK');self.assertEqual(references(self.state,a),[])
    def test_engine_ledger_rollback_reverts_a_reference(self):
        import json
        from gaia.autonomy.lineage import engine_state_dir
        a=self.lineage()['lineage_id'];self.go(self.loop(a,factory=Promoting,promotion=True))
        ref=references(self.state,a,self.root)[0];engine=self.root/engine_state_dir(a);engine.mkdir(exist_ok=True)
        (engine/'ledger.jsonl').write_text(json.dumps({'event_type':'rollback','payload':{'from_version':ref['version_after']}})+'\n')
        self.assertEqual(references(self.state,a,self.root),[]);self.assertTrue(references(self.state,a))  # without the engine ledger it stays
        self.assertEqual(catalog(self.state,root=self.root)['references'],[])  # the public path applies it too
    def test_catalog_is_read_only(self):
        a=self.lineage()['lineage_id'];self.go(self.loop(a))
        before={str(p):p.read_bytes()for p in self.state.rglob('*')if p.is_file()}
        catalog(self.state);catalog(self.state,[a])
        self.assertEqual({str(p):p.read_bytes()for p in self.state.rglob('*')if p.is_file()},before)


if __name__=='__main__':unittest.main()

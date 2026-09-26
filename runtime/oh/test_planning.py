import json
import unittest
from pathlib import Path
from . import test_workflow as fixtures
from .workflow import start, choose, load_run
from .runner import run
from .storage import Refused


class PlanningTest(unittest.TestCase):
    setUp=fixtures.WorkflowTest.setUp
    git=fixtures.WorkflowTest.git
    event=fixtures.WorkflowTest.event

    def test_each_planning_workflow_reviews_external_artifact_without_product_commit(self):
        for index,workflow in enumerate(('propose','design')):
            original=self.git('rev-parse','HEAD')
            start(self.root,{'workflow':workflow,'tasks':[{'id':workflow,'title':'Plan work','instructions':'Assess the requested change'}]},self.event(str(index)))
            roles=[]
            def fake(host,root,profile,prompt,role,directory,context,**kwargs):
                roles.append(role)
                if role=='review':
                    admission=json.loads((Path(directory)/'request.json').read_text())
                    artifact=Path(admission['artifact']['path'])
                    self.assertFalse(artifact.is_relative_to(root))
                    self.assertIn('Read-only plan',artifact.read_text())
                return {'failed':False,'returncode':0,'duration_ms':1,'text':'Read-only plan',
                    'structured':{'verdict':'clean','summary':'Reviewed plan','findings':[],'evidence':fixtures.EVIDENCE},'usage_observed':False}
            result=run(self.root,fake)
            self.assertEqual(result['status'],'completed')
            self.assertEqual(roles,['analysis','review'])
            self.assertEqual(self.git('rev-parse','HEAD'),original)
            self.assertEqual(self.git('status','--porcelain'),'')
            with self.assertRaises(Refused):choose(self.root,'pr',self.event('publish-'+str(index),'pr'))

    def test_analysis_that_changes_product_does_not_receive_review_or_completion(self):
        start(self.root,{'workflow':'propose','tasks':[{'id':'p','title':'Plan','instructions':'Propose only'}]},self.event())
        def mutation(host,root,profile,prompt,role,directory,context,**kwargs):
            self.assertEqual(role,'analysis')
            (root/'unexpected').write_text('preserve for inspection')
            return {'failed':False,'returncode':0,'duration_ms':1,'text':'changed','structured':None,'usage_observed':False}
        result=run(self.root,mutation)
        self.assertEqual(result['status'],'needs_attention')
        self.assertEqual(result['completed'],0)

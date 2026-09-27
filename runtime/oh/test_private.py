import json
from pathlib import Path
import unittest
from unittest.mock import patch
from . import plans
from .config import change
from .storage import Refused,Journal
from .workflow import choose,load_run
from .runner import run
from .test_design import design
from .test_propose import idea
from . import test_design as design_fixtures, test_propose as proposal_fixtures
from . import test_workflow as fixtures


class PrivatePlansTest(unittest.TestCase):
    git=fixtures.WorkflowTest.git
    event=fixtures.WorkflowTest.event
    worker=design_fixtures.DesignRunTest.worker
    design_run=design_fixtures.DesignRunTest.design_run

    def setUp(self):
        fixtures.WorkflowTest.setUp(self)
        self.git('switch','-q','main')
        change(self.root,'plans.private_folder',str(Path(self.temp.name)/'visible plans'))
        change(self.root,'plans.location','private')
        self.where=plans.layout(self.root)
        plans.start_roadmap(self.where,'Fixture')
        plans.add_milestone(self.root,self.where,'M1','First slice','Sign-in works')
        plans.add_initiative(self.root,self.where,'M1','auth','Sign-in',[])
        self.calls=[]

    def say(self,text):return choose(self.root,text,self.event(text,text))

    def test_private_design_waits_for_hash_bound_human_approval_without_git_changes(self):
        head=self.git('rev-parse','HEAD');self.design_run()
        result=run(self.root,self.worker([design()]))
        self.assertEqual(result['status'],'approval_checkpoint')
        path=self.where['designs']/'0001-auth.md'
        self.assertIn('status: draft',path.read_text())
        self.assertIn('approve',result['plan']['choices'])
        self.assertEqual(result['plan']['path'],str(path))
        journal,state=load_run(self.root);review=state['attempts'][-1]
        self.assertEqual(review['artifact']['files'][str(path)],plans.digest_of(path))
        self.say('approve')
        self.assertEqual(run(self.root,self.worker([]))['status'],'completed')
        self.assertEqual(plans.approval(self.root,self.where,'0001'),'approved')
        self.assertEqual(self.git('rev-parse','HEAD'),head)
        self.assertEqual(self.git('status','--porcelain'),'')
        path.write_text(path.read_text()+'\nHuman edit\n')
        self.assertEqual(plans.listing(self.root)['initiatives'][0]['status'],'edited since approval')

    def test_private_reconsider_restores_every_plan_file(self):
        before=self.where['roadmap'].read_bytes()
        self.where['roadmap'].chmod(0o600)
        mode=self.where['roadmap'].stat().st_mode & 0o777
        self.design_run();run(self.root,self.worker([design()]))
        self.say('reconsider')
        self.assertEqual(load_run(self.root)[1]['status'],'stopped')
        self.assertEqual(self.where['roadmap'].read_bytes(),before)
        self.assertEqual(self.where['roadmap'].stat().st_mode & 0o777,mode)
        self.assertFalse((self.where['designs']/'0001-auth.md').exists())
        self.assertEqual(self.git('branch','--show-current'),'main')

    def test_private_approval_and_reconsider_preserve_a_human_mode_change(self):
        self.design_run();run(self.root,self.worker([design()]))
        path=self.where['designs']/'0001-auth.md';path.chmod(0o444)
        self.addCleanup(path.chmod,0o600)
        mode=path.stat().st_mode & 0o777
        with self.assertRaisesRegex(Refused,'file type, mode or content'):self.say('reconsider')
        self.say('approve')
        with self.assertRaisesRegex(Refused,'file type, mode or content'):run(self.root,self.worker([]))
        self.assertEqual(path.stat().st_mode & 0o777,mode)
        self.assertEqual(plans.approval(self.root,self.where,'0001'),'draft')

    def test_private_paths_refuse_escaping_names_and_checkout_storage(self):
        for name in ('../escape','a/b','a\\b','..','CON','name.'):
            with self.assertRaisesRegex(Refused,'portable folder name'):plans.private_base(self.temp.name,name)
        change(self.root,'plans.private_folder',str(self.root/'private'))
        with self.assertRaisesRegex(Refused,'outside the project'):plans.layout(self.root)

    def test_rename_retains_private_documents_even_if_new_folder_exists(self):
        from .registry import rename
        before=self.where['roadmap'].read_bytes()
        (self.where['base'].parent/'Renamed').mkdir()
        rename(self.root,'Renamed')
        self.assertEqual(plans.layout(self.root)['roadmap'],self.where['roadmap'])
        self.assertEqual(self.where['roadmap'].read_bytes(),before)

    def test_replacement_keeps_private_documents_without_old_approval_authority(self):
        from .registry import register,lookup
        old=lookup(self.root);before=self.where['roadmap'].read_bytes()
        (self.root/'.git').rename(Path(self.temp.name)/'old-git')
        self.git('init','-q')
        new=register(self.root,'Replacement',replace=True)
        change(self.root,'plans.location','private')
        self.assertNotEqual(lookup(self.root)['checkout'],old['checkout'])
        self.assertNotEqual(new['id'],old['project'])
        self.assertEqual(plans.layout(self.root)['roadmap'],self.where['roadmap'])
        self.assertEqual(self.where['roadmap'].read_bytes(),before)
        self.assertFalse(plans.approvals_file(self.root).exists())

    def test_profile_export_explicitly_excludes_private_documents(self):
        from .profiles import export_profile
        change(self.root,'checks','[]')
        target=Path(self.temp.name)/'portable.json'
        result=export_profile(self.root,target)
        self.assertIn('private plan documents and their approvals are excluded',result['contents'])
        self.assertNotIn('Sign-in',target.read_text())

    def other_repository(self,name):
        import subprocess
        path=Path(self.temp.name)/name;path.mkdir()
        subprocess.run(['git','init','-q',str(path)],check=True)
        return path

    def test_renamed_folder_cannot_be_taken_by_a_new_project(self):
        from .registry import rename,register,index_path
        from .config import change
        change(self.root,'plans.private_folder',str(self.where['base'].parent),scope='global')
        change(self.root,'plans.location','private',scope='global')
        rename(self.root,'Renamed')
        other=self.other_repository('other')
        with self.assertRaisesRegex(Refused,'belongs to another project'):register(other,'Fixture')
        self.assertFalse(index_path(other).exists())
        self.assertEqual(plans.layout(self.root)['base'],self.where['base'])

    def test_case_aliases_and_unowned_folders_are_refused(self):
        from .registry import register
        other=self.other_repository('other');register(other,'fixture')
        change(other,'plans.private_folder',str(self.where['base'].parent))
        change(other,'plans.location','private')
        with self.assertRaisesRegex(Refused,'belongs to another project'):plans.layout(other)
        folder=Path(self.temp.name)/'existing';(folder/'fixture').mkdir(parents=True)
        change(other,'plans.private_folder',str(folder))
        with self.assertRaisesRegex(Refused,'without ownership'):plans.layout(other)

    def test_import_does_not_adopt_deleted_projects_private_documents(self):
        from .registry import index_path
        from .profiles import export_profile,import_profile
        import shutil
        change(self.root,'checks','[]')
        target=Path(self.temp.name)/'profile.json';export_profile(self.root,target)
        before=self.where['roadmap'].read_bytes();shutil.rmtree(self.root)
        other=self.other_repository('other')
        with self.assertRaisesRegex(Refused,'belongs to another project'):import_profile(other,target)
        self.assertFalse(index_path(other).exists())
        self.assertEqual(self.where['roadmap'].read_bytes(),before)

    def test_private_edits_use_the_canonical_folder_lock(self):
        from . import private_storage
        from .storage import lock
        expected=private_storage.folder_lock(self.where['base']);seen=[]
        def observe(path,**kwargs):
            seen.append(path)
            return lock(path,**kwargs)
        with patch('oh.storage.lock',observe),plans.editing(self.root):
            with plans.editing(self.root):pass
        self.assertEqual(seen.count(expected),1)
        self.assertEqual(private_storage.canonical(self.where['base']),private_storage.canonical(str(self.where['base']).upper()))

    def test_closed_private_designs_cannot_be_reapproved(self):
        from .workflow import active_file
        for status in ('frozen','abandoned'):
            with self.subTest(status=status):
                path=Path(plans.write_design(self.root,self.where,'auth','Auth',design()['body'],'draft')[1])
                if not plans.initiative(self.root,self.where,'auth',named=True)['design']:
                    plans.claim(self.root,self.where,'auth','0001')
                path.write_bytes(path.read_bytes().replace(b'status: draft',('status: '+status).encode()).replace(b'- [ ]',b'- [x]'))
                before=path.read_bytes()
                with self.assertRaisesRegex(Refused,'only draft or edited since approval'):self.design_run()
                self.assertFalse(active_file(self.root).exists());self.assertEqual(self.calls,[])
                self.assertEqual(path.read_bytes(),before)
                path.unlink()

    def test_approval_checks_the_approved_postimage_before_publication(self):
        self.design_run();run(self.root,self.worker([design()]));self.say('approve')
        path=self.where['designs']/'0001-auth.md';before=path.read_bytes()
        original=plans.verify_design;postimages=[]
        def reject(root,where,number=None,**kwargs):
            if where['designs']!=self.where['designs']:
                postimages.append((Path(where['designs'])/path.name).read_bytes())
                raise Refused('invalid approved postimage')
            return original(root,where,number,**kwargs)
        with patch.object(plans,'verify_design',reject):
            with self.assertRaisesRegex(Refused,'invalid approved postimage'):run(self.root,self.worker([]))
        self.assertEqual(len(postimages),1);self.assertIn(b'status: approved',postimages[0])
        self.assertEqual(path.read_bytes(),before)
        self.assertNotIn('private_approval',load_run(self.root)[1])
        self.assertFalse(plans.approvals_file(self.root).exists())

    def test_private_proposal_exposes_complete_multi_file_diff(self):
        proposal_fixtures.ProposeTest.propose(self,'Search notes')
        value=idea(decision_title='Which index?',decision_context='Keep notes isolated.',
                   decision_alternatives='Shared or separate indexes.',decision_consequences='Storage changes.')
        result=run(self.root,proposal_fixtures.ProposeTest.worker(self,[value]))
        diff=result['private_diff']
        self.assertIn('+| `search` |',diff)
        self.assertIn('+Keep notes isolated.',diff)
        self.assertIn('+Shared or separate indexes.',diff)
        self.assertIn('+Storage changes.',diff)
        self.assertEqual(diff,plans.changed_text(self.root,load_run(self.root)[1]['rendered']))
        self.assertEqual(self.git('status','--porcelain'),'')

    def test_approval_refuses_a_file_changed_after_review(self):
        self.design_run();run(self.root,self.worker([design()]))
        path=self.where['designs']/'0001-auth.md';path.write_text(path.read_text()+'\nHuman edit\n')
        self.say('approve')
        with self.assertRaisesRegex(Refused,'changed after'):run(self.root,self.worker([]))
        self.assertIn('Human edit',path.read_text())
        self.assertNotEqual(plans.approval(self.root,self.where,'0001'),'approved')

    def test_private_scope_edit_stops_before_the_worker(self):
        self.design_run()
        self.where['roadmap'].write_text(self.where['roadmap'].read_text().replace('Sign-in','Different scope'))
        with self.assertRaisesRegex(Refused,'Private plan files changed'):run(self.root,self.worker([design()]))
        self.assertEqual(self.calls,[])

    def test_private_scope_deletion_stops_before_the_worker(self):
        self.design_run();self.where['roadmap'].unlink()
        with self.assertRaisesRegex(Refused,'Private plan files changed'):run(self.root,self.worker([design()]))
        self.assertEqual(self.calls,[])

    def test_edited_design_retries_failed_review_without_rewriting_human_prose(self):
        self.design_run();run(self.root,self.worker([design()]));self.say('approve');run(self.root,self.worker([]))
        path=self.where['designs']/'0001-auth.md';path.write_text(path.read_text()+'\nA human rationale.\n')
        before=path.read_bytes();self.calls=[]
        self.design_run(turn='2')
        normal=self.worker([]);failed=[False]
        def retry(*args,**kwargs):
            if not failed[0]:
                failed[0]=True
                self.assertEqual(args[4],'review')
                return {'failed':True,'returncode':1,'text':'unavailable','structured':None,'duration_ms':1,'usage_observed':False}
            return normal(*args,**kwargs)
        self.assertEqual(run(self.root,retry)['status'],'approval_checkpoint')
        self.assertEqual(path.read_bytes(),before)
        self.assertEqual([c[0] for c in self.calls],['review'])
        self.say('approve');self.assertEqual(run(self.root,self.worker([]))['status'],'completed')
        self.assertEqual(plans.approval(self.root,self.where,'0001'),'approved')

    def test_private_analysis_cannot_mutate_other_planning_context(self):
        self.design_run();normal=self.worker([design()])
        def mutate(*args,**kwargs):
            result=normal(*args,**kwargs)
            self.where['roadmap'].write_text(self.where['roadmap'].read_text()+'\nMutated context\n')
            return result
        self.assertEqual(run(self.root,mutate)['status'],'needs_attention')
        self.assertEqual(load_run(self.root)[1]['attempts'][-1]['outcome'],'analysis_mutated_tree')

    def test_private_reviewer_cannot_mutate_the_plan_and_approve_it(self):
        self.design_run();normal=self.worker([design()])
        def mutate(*args,**kwargs):
            result=normal(*args,**kwargs)
            if args[4]=='review':
                path=self.where['designs']/'0001-auth.md';path.write_text(path.read_text()+'\nReview mutation\n')
            return result
        result=run(self.root,mutate)
        self.assertEqual(result['status'],'needs_attention')
        self.assertEqual(load_run(self.root)[1]['attempts'][-1]['outcome'],'review_mutated_tree')

    def test_approval_publication_recovers_without_another_worker_or_grant(self):
        self.design_run();run(self.root,self.worker([design()]))
        self.say('approve');original=Journal.append
        def interrupt(journal,kind,data):
            if kind=='task.completed':raise OSError('publication interrupted')
            return original(journal,kind,data)
        with patch.object(Journal,'append',interrupt):
            with self.assertRaisesRegex(OSError,'publication interrupted'):run(self.root,self.worker([]))
        self.assertEqual(run(self.root,self.worker([]))['status'],'completed')
        self.assertEqual(plans.approval(self.root,self.where,'0001'),'approved')
        self.assertEqual([c[0] for c in self.calls],['analysis','review'])

    def test_private_proposal_adds_a_task_and_renews_approval_only_after_the_gate(self):
        self.design_run();run(self.root,self.worker([design()]));self.say('approve');run(self.root,self.worker([]))
        proposal_fixtures.ProposeTest.propose(self,'Rate limit sign-in')
        proposal_worker=proposal_fixtures.ProposeTest.worker(self,[idea('task')])
        result=run(self.root,proposal_worker)
        self.assertEqual(result['status'],'approval_checkpoint')
        self.assertEqual(plans.approval(self.root,self.where,'0001'),'edited since approval')
        self.say('approve');run(self.root,proposal_fixtures.ProposeTest.worker(self,[]))
        self.assertEqual(plans.approval(self.root,self.where,'0001'),'approved')
        self.assertEqual(self.git('status','--porcelain'),'')

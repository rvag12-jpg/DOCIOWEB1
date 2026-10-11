"""No real credentials, students, images or OpenAI requests are used."""
import copy
import io
import json
import os
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch
import httpx
from PIL import Image
from fastapi.testclient import TestClient
from app.main import app
from app import repository as repo
from app.storage import store
from app.api import documents
from app.services import ai_jobs,ai_provider
from app.services.corrector import Framework,StudentResult


class AITests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)/'images';self.root.mkdir()
        patches=[patch.object(repo,'DB_PATH',Path(self.temp.name)/'test.sqlite3'),
                 patch.object(repo,'LEGACY_PATH',Path(self.temp.name)/'absent.json'),
                 patch.object(repo,'POSTGRES',False),patch.object(repo,'DEMO_MODE',True),
                 patch.object(store,'root',self.root),
                 patch.object(documents,'settings',replace(documents.settings,data_dir=self.root)),
                 patch.dict(os.environ,{'DOCIO_AI_PROVIDER':'mock','OPENAI_API_KEY':'','DOCIO_AI_ACCESS_TOKEN':''}),
                 patch.object(ai_jobs,'enqueue')]
        for active in patches:active.start();self.addCleanup(active.stop)
        self.client=TestClient(app)
        self.document=self.client.post('/api/v1/ai/demo-images').json()
        self.framework=self.client.get('/api/v1/ai/framework/DEMO-FOLLOWUP').json()
        self.original_correct=ai_provider.correct

    def payload(self,ids=('DEMO-001',),**changes):
        return {'request_id':'synthetic-job-0001','source_assessment_id':'DEMO-FOLLOWUP',
                'title':'Prueba IA completamente ficticia','evaluation':'1ª','assessment_date':'2026-10-11',
                'framework':copy.deepcopy(self.framework),'framework_confirmed':True,
                'assignments':[{'student_id':sid,'document_id':self.document['document_id']} for sid in ids],**changes}

    def create(self,**changes):
        response=self.client.post('/api/v1/ai/jobs',json=self.payload(**changes))
        self.assertEqual(response.status_code,201,response.text)
        return response.json()

    def process(self,job):
        ai_jobs.run_job(job['job_id'])
        return self.client.get('/api/v1/ai/jobs/'+job['job_id']).json()

    def corrections(self,job):
        return self.client.get('/api/v1/docio/export/'+job['assessment_id']).json()['corrections']

    def test_mock_job_creates_new_assessment_and_loads_drafts_without_network(self):
        before=repo.state()['corrections']
        job=self.create(ids=('DEMO-001','DEMO-002','DEMO-003'))
        with patch.object(ai_provider.httpx,'Client',side_effect=AssertionError('Mock cannot call OpenAI')):
            result=self.process(job)
        self.assertEqual(result['status'],'completed');self.assertEqual(result['completed'],3)
        rows=self.corrections(job)
        self.assertEqual(len(rows),3)
        self.assertTrue(all(r['final_score']==6.5 and not r['validated'] and r['ai_report']['simulated'] for r in rows))
        for row in rows:
            page=int(row['student_id'][-1])
            self.assertEqual(row['ai_report']['source_pages'],[{'page_number':page,'image_url':f'/media/{self.document["document_id"]}/pages/page-{page:04d}.jpg'}])
        self.assertEqual([c for c in repo.state()['corrections'] if c['assessment_id']!=job['assessment_id']],before)
        self.assertEqual(self.client.get('/api/v1/docio/analytics/'+job['assessment_id']).json()['students'],[])
        self.assertNotIn('ai_jobs',self.client.get('/api/v1/docio/state').json())
        self.assertNotIn('images',result['students'][0])

    def test_start_is_idempotent_and_completed_job_never_calls_provider_again(self):
        job=self.create()
        again=self.create()
        self.assertEqual(job['assessment_id'],again['assessment_id'])
        self.assertEqual(len(repo.state()['assessments']),3)
        self.process(job)
        with patch.object(ai_provider,'correct',side_effect=AssertionError('Already finished')):
            self.assertEqual(self.process(job)['completed'],1)
        response=self.client.post('/api/v1/ai/jobs',json=self.payload(title='Otro título ficticio'))
        self.assertEqual(response.status_code,409)

    def test_invalid_or_unconfirmed_framework_does_not_create_an_assessment(self):
        before=repo.state()['assessments']
        unconfirmed=self.payload(framework_confirmed=False)
        weights=self.payload();weights['framework']['questions'][0]['components'][0]['max_points']=1
        no_answer=self.payload();no_answer['framework']['questions'][0]['expected_answer']=' '
        duplicate=self.payload();duplicate['framework']['questions'].append(duplicate['framework']['questions'][0])
        for payload in (unconfirmed,weights,no_answer,duplicate):
            with self.subTest(payload=payload):
                self.assertEqual(self.client.post('/api/v1/ai/jobs',json=payload).status_code,422)
        self.assertEqual(repo.state()['assessments'],before)

    def test_curriculum_relations_are_required_and_not_inferred(self):
        repo.remove('relations','DEMO-K1::DEMO-C1')
        response=self.client.post('/api/v1/ai/jobs',json=self.payload())
        self.assertEqual(response.status_code,422)
        self.assertEqual(len(repo.state()['assessments']),2)

    def test_duplicate_or_unassigned_students_are_rejected(self):
        for ids in (('DEMO-001','DEMO-001'),('DEMO-004',)):
            self.assertEqual(self.client.post('/api/v1/ai/jobs',json=self.payload(ids)).status_code,422)
        repo.put('students',{'student_id':'DEMO-OUTSIDE','group_id':'DEMO-OTHER'})
        self.assertEqual(self.client.post('/api/v1/ai/jobs',json=self.payload(('DEMO-OUTSIDE',))).status_code,422)

    def test_partial_failure_retry_calls_only_failed_student(self):
        job=self.create(ids=('DEMO-001','DEMO-002'))
        calls=[]
        def provider(sid,*args):
            calls.append(sid)
            if sid=='DEMO-002':raise ai_provider.ProviderError('Synthetic transport error')
            return self.original_correct(sid,*args)
        with patch.object(ai_provider,'correct',side_effect=provider):result=self.process(job)
        self.assertEqual(result['status'],'partial');self.assertEqual(result['completed'],1)
        first=copy.deepcopy(self.corrections(job)[0])
        self.assertEqual(self.client.post('/api/v1/ai/jobs/'+job['job_id']+'/retry').status_code,200)
        with patch.object(ai_provider,'correct',wraps=self.original_correct) as provider:
            self.assertEqual(self.process(job)['completed'],2)
            self.assertEqual(provider.call_count,1)
            self.assertEqual(provider.call_args.args[0],'DEMO-002')
        self.assertEqual(self.corrections(job)[0],first)

    def test_unreadable_answer_has_no_fabricated_score_and_requires_review(self):
        job=self.create()
        def unreadable(*args):
            result,metadata=self.original_correct(*args)
            data=result.model_dump()
            for item in data['items']:
                item.update(transcription='[ILEGIBLE]',legibility='ilegible',confidence=.2)
                for component in item['components']:
                    component.update(awarded=None,observed_evidence=['[ILEGIBLE] Sin evidencia recuperable.'])
            return StudentResult.model_validate(data),metadata
        with patch.object(ai_provider,'correct',side_effect=unreadable):result=self.process(job)
        self.assertEqual(result['students'][0]['status'],'review_required')
        row=self.corrections(job)[0]
        self.assertEqual(row['scores'],{});self.assertIsNone(row['final_score'])
        self.assertFalse(row['validated'])
        self.assertTrue(row['ai_report']['review_reasons'])
        payload=self.client.get('/api/v1/docio/export/'+job['assessment_id']).json()
        preview=self.client.post('/api/v1/docio/import/preview',json=payload)
        self.assertEqual(preview.status_code,200,preview.text)
        self.assertIsNone(preview.json()['changes'][0]['final_score'])
        imported=self.client.post('/api/v1/docio/import',json={**payload,'expected_revision':preview.json()['revision']})
        self.assertEqual(imported.status_code,200,imported.text)
        self.assertIsNone(self.corrections(job)[0]['final_score'])
        saved=self.client.put('/api/v1/docio/corrections',json={
            'assessment_id':job['assessment_id'],'student_id':'DEMO-001','scores':{},'validated':False})
        self.assertEqual(saved.status_code,200,saved.text)
        self.assertIsNone(saved.json()['final_score'])

    def test_wrong_identity_question_component_or_page_is_not_loaded(self):
        for index,field in enumerate(('student','question','component','page','score')):
            job=self.create(request_id=f'synthetic-invalid-{index}')
            def invalid(*args):
                result,metadata=self.original_correct(*args);data=result.model_dump()
                if field=='student':data['student_id']='DEMO-OTHER'
                if field=='question':data['items'].pop()
                if field=='component':data['items'][0]['components'][0]['component_id']='OTHER'
                if field=='page':data['items'][0]['page_numbers']=[999]
                if field=='score':data['items'][0]['components'][0]['awarded']=99
                return StudentResult.model_validate(data),metadata
            with patch.object(ai_provider,'correct',side_effect=invalid):result=self.process(job)
            self.assertEqual(result['status'],'failed',field)
            self.assertEqual(self.corrections(job),[],field)

    def test_equivalent_evidence_with_different_scores_requires_consistency_review(self):
        job=self.create(ids=('DEMO-001','DEMO-002'))
        def inconsistent(sid,*args):
            result,metadata=self.original_correct(sid,*args);data=result.model_dump()
            if sid=='DEMO-002':data['items'][0]['components'][0]['awarded']=1
            return StudentResult.model_validate(data),metadata
        with patch.object(ai_provider,'correct',side_effect=inconsistent):result=self.process(job)
        self.assertTrue(all(s['status']=='review_required' for s in result['students']))
        self.assertTrue(all(any('Consistencia' in reason for reason in s['review_reasons']) for s in result['students']))

    def test_missing_or_changed_images_fail_before_a_provider_call(self):
        job=self.create()
        record=repo.get_record('ai_jobs',job['job_id']);image=self.root/record['students'][0]['images'][0]['path']
        image.write_bytes(b'Synthetic changed image')
        with patch.object(ai_provider,'correct',side_effect=AssertionError('Must check source first')):
            self.assertEqual(self.process(job)['status'],'failed')
        self.assertEqual(self.corrections(job),[])

    def test_model_result_and_checkpoint_are_atomic(self):
        job=self.create();original=repo._put
        def fail_checkpoint(connection,collection,key,row,action='upsert'):
            original(connection,collection,key,row,action)
            if action=='ai-checkpoint' and row['students'][0]['status']=='completed':
                raise RuntimeError('Synthetic checkpoint failure')
        with patch.object(repo,'_put',side_effect=fail_checkpoint):result=self.process(job)
        self.assertEqual(result['status'],'interrupted')
        self.assertEqual(self.corrections(job),[])
        self.assertEqual(result['completed'],0)

    def test_human_review_is_explicit_and_preserves_original_model_report(self):
        job=self.create();self.process(job);before=self.corrections(job)[0]
        payload={'assessment_id':job['assessment_id'],'student_id':'DEMO-001','scores':{'Q1':1,'Q2':1},'validated':True}
        self.assertEqual(self.client.put('/api/v1/docio/corrections',json=payload).status_code,422)
        response=self.client.put('/api/v1/docio/corrections',json={**payload,'teacher_review_confirmed':True})
        self.assertEqual(response.status_code,200,response.text)
        self.assertEqual(response.json()['final_score'],5)
        self.assertEqual(response.json()['ai_report']['result'],before['ai_report']['result'])
        self.assertTrue(response.json()['ai_report']['teacher_validated'])
        self.assertEqual(response.json()['ai_report']['status'],'CLOSED')

    def test_simulation_cannot_validate_a_standard_assessment(self):
        job=self.create();self.process(job)
        # Copy only synthetic fixtures into isolated standard tables for this check.
        state=repo.state()
        with patch.object(repo,'DEMO_MODE',False):
            for collection,rows in state.items():
                for row in rows:repo.put(collection,row)
            payload={'assessment_id':job['assessment_id'],'student_id':'DEMO-001','scores':{'Q1':1,'Q2':1},'validated':True,'teacher_review_confirmed':True}
            self.assertEqual(self.client.put('/api/v1/docio/corrections',json=payload).status_code,422)

    def upload_image(self,sid,document_id=None,data=None):
        if data is None:
            buffer=io.BytesIO();Image.new('RGB',(200,250),'white').save(buffer,'PNG');data=buffer.getvalue()
        upload=self.client.post('/api/v1/documents/chunked/init').json()['upload_id']
        middle=len(data)//2
        for i,part in enumerate((data[:middle],data[middle:])):
            self.assertEqual(self.client.post(f'/api/v1/documents/chunked/{upload}/part/{i}',content=part).status_code,200)
        return self.client.post(f'/api/v1/documents/chunked/{upload}/image-complete',json={'student_id':sid,'document_id':document_id,'size':len(data),'chunks':2})

    def test_direct_images_are_reconstructed_assigned_and_appended_in_order(self):
        first=self.upload_image('DEMO-001');self.assertEqual(first.status_code,201,first.text)
        document=first.json()
        second=self.upload_image('DEMO-001',document['document_id']);self.assertEqual(second.status_code,201,second.text)
        self.assertEqual(second.json()['page_count'],2)
        self.assertEqual([p['page_number'] for p in second.json()['segments'][0]['pages']],[1,2])
        self.assertEqual(self.upload_image('DEMO-002',document['document_id']).status_code,422)
        self.assertEqual(store.load_manifest(document['document_id']).page_count,2)
        self.assertEqual(self.upload_image('DEMO-001',data=b'Invented non-image bytes').status_code,422)

    def test_real_mode_requires_server_credentials_and_authorized_access(self):
        with patch.dict(os.environ,{'DOCIO_AI_PROVIDER':'openai','OPENAI_API_KEY':'replace_with_your_real_key','DOCIO_AI_ACCESS_TOKEN':'replace_with_a_random_access_token'}):
            self.assertFalse(self.client.get('/api/v1/ai/config').json()['ready'])
            self.assertEqual(self.client.post('/api/v1/ai/jobs',json=self.payload()).status_code,503)
        with patch.dict(os.environ,{'DOCIO_AI_PROVIDER':'openai','OPENAI_API_KEY':'sk-unit-test-key-0000000000','DOCIO_AI_ACCESS_TOKEN':'unit-test-access-code-0000000000'}):
            self.assertEqual(self.client.post('/api/v1/ai/jobs',json=self.payload()).status_code,401)
            response=self.client.post('/api/v1/ai/jobs',json=self.payload(),headers={'Authorization':'Bearer unit-test-access-code-0000000000'})
            self.assertEqual(response.status_code,201,response.text)
            text=self.client.get('/api/v1/ai/config').text
            self.assertNotIn('sk-unit-test',text);self.assertNotIn('unit-test-access-code',text)

    def test_responses_adapter_uses_private_images_strict_json_and_no_history(self):
        assessment=repo.get_record('assessments','DEMO-FOLLOWUP');framework=Framework.model_validate(self.framework)
        images=[(1,self.root/self.document['document_id']/'pages'/'page-0001.jpg')]
        mock_result,_=self.original_correct('DEMO-001',assessment,framework,images,'mock')
        captured=[];original_client=httpx.Client
        def handler(request):
            captured.append(json.loads(request.content))
            return httpx.Response(200,json={'id':'synthetic-response-id','model':'synthetic-model','status':'completed',
                                          'output':[{'content':[{'type':'output_text','text':mock_result.model_dump_json()}]}],
                                          'usage':{'input_tokens':100,'output_tokens':100}})
        def client(**kwargs):return original_client(transport=httpx.MockTransport(handler),**kwargs)
        with patch.dict(os.environ,{'DOCIO_AI_PROVIDER':'openai','OPENAI_API_KEY':'sk-unit-test-key-0000000000','DOCIO_AI_ACCESS_TOKEN':'unit-test-access-code-0000000000'}),patch.object(ai_provider.httpx,'Client',side_effect=client):
            result,metadata=ai_provider.correct('DEMO-001',assessment,framework,images)
        request=captured[0];self.assertFalse(request['store'])
        self.assertTrue(request['text']['format']['strict'])
        self.assertTrue(any(c['type']=='input_image' and c['image_url'].startswith('data:image/jpeg;base64,') for c in request['input'][0]['content']))
        self.assertNotIn('previous_response_id',request)
        self.assertNotIn('DEMO-002',json.dumps(request))
        self.assertEqual(result.student_id,'DEMO-001');self.assertFalse(metadata['simulated'])
        self.assertEqual(metadata['response_id'],'synthetic-response-id')

    def test_provider_failure_does_not_echo_credentials_or_import_incomplete_json(self):
        assessment=repo.get_record('assessments','DEMO-FOLLOWUP');framework=Framework.model_validate(self.framework)
        images=[(1,self.root/self.document['document_id']/'pages'/'page-0001.jpg')]
        original_client=httpx.Client
        for status,data in ((401,{'secret':'sk-unit-test-key-0000000000'}),(429,{}),(200,{'status':'incomplete','output':[]}),(200,{'status':'completed','output':[{'content':[{'type':'refusal'}]}]})):
            def client(**kwargs):return original_client(transport=httpx.MockTransport(lambda request:httpx.Response(status,json=data)),**kwargs)
            with patch.dict(os.environ,{'DOCIO_AI_PROVIDER':'openai','OPENAI_API_KEY':'sk-unit-test-key-0000000000','DOCIO_AI_ACCESS_TOKEN':'unit-test-access-code-0000000000'}),patch.object(ai_provider.httpx,'Client',side_effect=client),self.assertRaises(ai_provider.ProviderError) as error:
                ai_provider.correct('DEMO-001',assessment,framework,images)
            self.assertNotIn('sk-unit-test',str(error.exception))


if __name__=='__main__':unittest.main()

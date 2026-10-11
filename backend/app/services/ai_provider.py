"""Responses API adapter; mock mode never performs an external request."""
import base64
import json
import os
import httpx
from app import repository as repo
from app.services.corrector import INSTRUCTIONS, StudentResult


class ProviderError(RuntimeError):
    pass


def configuration():
    provider=os.getenv('DOCIO_AI_PROVIDER','mock' if repo.DEMO_MODE else 'openai').strip().lower()
    key=os.getenv('OPENAI_API_KEY','').strip()
    token=os.getenv('DOCIO_AI_ACCESS_TOKEN','').strip()
    usable=len(key)>=20 and not any(word in key.lower() for word in ('replace','placeholder','supuesta','your_real','ficticia'))
    access=len(token)>=24 and not any(word in token.lower() for word in ('replace','placeholder','supuesta','your_real','ficticia'))
    return {'provider':provider,'simulated':provider=='mock','model':os.getenv('DOCIO_AI_MODEL','gpt-6-astra'),
            'ready':provider=='mock' or (provider=='openai' and usable and access),
            'access_required':provider=='openai','key_configured':usable,'access_configured':access}


def build_request(student_id,assessment,framework,images):
    content=[{'type':'input_text','text':json.dumps({'student_id':student_id,
              'assessment':{'questions':assessment['questions'],'assessment_type':assessment.get('assessment_type','exam')},
              'framework':framework.model_dump()},ensure_ascii=False)}]
    for page,path in images:
        content.append({'type':'input_text','text':f'Página {page} del alumno {student_id}.'})
        content.append({'type':'input_image','detail':'high',
                        'image_url':'data:image/jpeg;base64,'+base64.b64encode(path.read_bytes()).decode('ascii')})
    return {'model':configuration()['model'],'store':False,'instructions':INSTRUCTIONS,
            'input':[{'role':'user','content':content}],
            'max_output_tokens':int(os.getenv('DOCIO_AI_MAX_OUTPUT_TOKENS','16000')),
            'text':{'format':{'type':'json_schema','name':'corrector_student_result','strict':True,
                              'schema':StudentResult.model_json_schema()}}}


def correct(student_id,assessment,framework,images,provider=None):
    mode=provider or configuration()['provider']
    if mode=='mock':
        items=[]
        for question in framework.questions:
            items.append({'question_id':question.question_id,'transcription':'[SIMULACIÓN] No se ha leído ni calificado la imagen.',
                          'legibility':'legible','confidence':1.0,'page_numbers':[p for p,_ in images],
                          'components':[{'component_id':c.component_id,'awarded':c.max_points*.65,
                                         'observed_evidence':['[SIMULACIÓN] Evidencia completamente ficticia.'],
                                         'justification':'Crédito inventado para verificar el recorrido de datos.'} for c in question.components],
                          'errors':[],'feedback':'[SIMULACIÓN] Feedback ficticio; no representa una evaluación.', 'review_reasons':[]})
        return StudentResult.model_validate({'student_id':student_id,'items':items,
                      'general_comment':'SIMULACIÓN: puntuaciones ficticias, sin llamada a OpenAI ni corrección del contenido.'}), {'model':'mock','response_id':None,'usage':None,'simulated':True}
    if mode!='openai' or not configuration()['ready']:
        raise ProviderError('El proveedor OpenAI no está configurado')
    try:
        # Deliberately no automatic retries: an ambiguous timeout may already be billed.
        with httpx.Client(timeout=httpx.Timeout(180,connect=10,write=30,pool=10),follow_redirects=False) as client:
            response=client.post('https://api.openai.com/v1/responses',
                                 headers={'Authorization':'Bearer '+os.environ['OPENAI_API_KEY']},
                                 json=build_request(student_id,assessment,framework,images))
        if response.status_code in (401,403):
            raise ProviderError('OpenAI rechazó las credenciales o el acceso al modelo')
        if response.status_code==429:
            raise ProviderError('OpenAI ha alcanzado un límite de uso o de cuota; revise la cuenta antes de reintentar')
        if not response.is_success:
            raise ProviderError(f'OpenAI devolvió HTTP {response.status_code}; el alumno queda pendiente')
        data=response.json()
        if data.get('status')!='completed':
            raise ProviderError('OpenAI no completó la respuesta; no se ha importado una corrección parcial')
        texts=[]
        for output in data.get('output',[]):
            for part in output.get('content',[]):
                if part.get('type')=='refusal':
                    raise ProviderError('OpenAI rechazó la corrección de este contenido')
                if part.get('type')=='output_text':
                    texts.append(part.get('text',''))
        result=StudentResult.model_validate_json(''.join(texts))
        return result,{'model':data.get('model',configuration()['model']), 'response_id':data.get('id'),
                       'usage':data.get('usage'),'simulated':False}
    except httpx.TimeoutException as error:
        raise ProviderError('Tiempo de espera agotado. La solicitud puede haber sido procesada; el reintento es manual') from error
    except httpx.HTTPError as error:
        raise ProviderError('No se pudo conectar con OpenAI; no se ha importado el resultado') from error
    except (ValueError,KeyError,TypeError) as error:
        raise ProviderError('La respuesta de OpenAI no cumple el formato de CORRECTOR') from error

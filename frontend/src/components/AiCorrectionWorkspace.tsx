import {useEffect,useRef,useState} from 'react';
import {requestDocio as api,uploadStudentImages} from '../api';
import {PdfUpload} from './PdfUpload';
import {StudentSegmentsView} from './StudentSegmentsView';
import {AssessmentMetaFields,localToday} from './AssessmentForm';
import type {DocumentView} from '../types';

type DocSummary={document_id:string;original_filename:string;segments:{student_key:string|null;start_page:number;end_page:number}[]};
const statusNames:Record<string,string>={queued:'En cola',running:'Corrigiendo',completed:'Propuestas cargadas',partial:'Completado con errores',failed:'No completado',interrupted:'Interrumpido',pending:'Pendiente',review_required:'Revisión necesaria'};

export function AiCorrectionWorkspace({db,reload,openCorrection}:{db:any;reload:()=>Promise<void>;openCorrection:(id:string)=>void}){
  const [config,setConfig]=useState<any>(null),[documents,setDocuments]=useState<DocSummary[]>([]);
  const [aid,setAid]=useState(''),[meta,setMeta]=useState<any>({title:'',evaluation:'1ª',assessment_date:localToday()});
  const [rubric,setRubric]=useState(''),[confirmed,setConfirmed]=useState(false),[selected,setSelected]=useState<Record<string,string>>({});
  const [studentId,setStudentId]=useState(''),[images,setImages]=useState<File[]>([]),[pdf,setPdf]=useState<DocumentView|null>(null);
  const [busy,setBusy]=useState(false),[error,setError]=useState(''),[token,setToken]=useState('');
  const [job,setJob]=useState<any>(null),[history,setHistory]=useState<any[]>([]),[pollVersion,setPollVersion]=useState(0);
  const requestId=useRef<string|null>(null);
  const source=db.assessments.find((a:any)=>a.assessment_id===aid);
  const students=db.students.filter((s:any)=>source&&s.group_id===source.group_id);
  const headers=():Record<string,string>=>token?{Authorization:'Bearer '+token}:{};
  const invalidate=()=>{setConfirmed(false);requestId.current=null;setError('')};
  async function refreshDocuments(){setDocuments(await api('/documents'))}
  async function refreshHistory(){try{setHistory(await api('/ai/jobs',{headers:headers()}))}catch(e){setError((e as Error).message)}}
  useEffect(()=>{
    const controller=new AbortController();
    void Promise.all([api('/ai/config',{signal:controller.signal}),api('/documents',{signal:controller.signal})]).then(([c,docs])=>{
      setConfig(c);setDocuments(docs);
      if(!c.access_required)void api('/ai/jobs',{signal:controller.signal}).then(setHistory).catch(e=>{if(!controller.signal.aborted)setError(e.message)});
    }).catch(e=>{if(!controller.signal.aborted)setError(e.message)});
    return()=>controller.abort();
  },[]);
  useEffect(()=>{
    if(!job?.job_id)return;
    const controller=new AbortController();let inFlight=false,finished=false;
    const poll=async()=>{
      if(inFlight||finished)return;inFlight=true;
      try{
        const data=await api('/ai/jobs/'+encodeURIComponent(job.job_id),{headers:headers(),signal:controller.signal});
        if(controller.signal.aborted)return;
        setJob(data);
        if(!['queued','running'].includes(data.status)){finished=true;await reload();await refreshHistory()}
      }catch(e){if(!controller.signal.aborted)setError((e as Error).message)}finally{inFlight=false}
    };
    void poll();const interval=setInterval(()=>void poll(),2500);
    return()=>{controller.abort();clearInterval(interval)};
  },[job?.job_id,token,pollVersion]);
  async function chooseSource(id:string){
    setAid(id);setSelected({});setStudentId('');setRubric('');invalidate();
    if(!id)return;
    setBusy(true);
    try{
      const a=db.assessments.find((a:any)=>a.assessment_id===id);
      setMeta({title:a.title+' · corrección IA',evaluation:a.evaluation,assessment_date:localToday()});
      setRubric(JSON.stringify(await api('/ai/framework/'+encodeURIComponent(id)),null,2));
    }catch(e){setError((e as Error).message)}finally{setBusy(false)}
  }
  async function uploadImages(){
    setBusy(true);setError('');
    try{
      const doc=await uploadStudentImages(images,studentId);
      await refreshDocuments();setSelected(old=>({...old,[studentId]:doc.document_id}));invalidate();setImages([]);
    }catch(e){setError((e as Error).message)}finally{setBusy(false)}
  }
  async function demo(){
    setBusy(true);setError('');
    try{
      const template=db.assessments.find((a:any)=>a.assessment_id==='DEMO-FOLLOWUP');
      if(!template)throw new Error('No se encuentra la plantilla DEMO de seguimiento.');
      setAid(template.assessment_id);setMeta({title:'Corrección IA · lote ficticio',evaluation:'1ª',assessment_date:localToday()});
      setRubric(JSON.stringify(await api('/ai/framework/'+template.assessment_id),null,2));
      const doc=await api('/ai/demo-images',{method:'POST'});
      await refreshDocuments();setSelected(Object.fromEntries(doc.segments.map((s:any)=>[s.student_key,doc.document_id])));
      invalidate();
    }catch(e){setError((e as Error).message)}finally{setBusy(false)}
  }
  async function start(){
    setBusy(true);setError('');
    try{
      if(!requestId.current)requestId.current=crypto.randomUUID();
      const result=await api('/ai/jobs',{method:'POST',headers:headers(),body:JSON.stringify({
        request_id:requestId.current,source_assessment_id:aid,...meta,framework:JSON.parse(rubric),framework_confirmed:confirmed,
        assignments:Object.entries(selected).map(([student_id,document_id])=>({student_id,document_id}))
      })});
      setJob(result);await reload();await refreshHistory();
    }catch(e){setError(e instanceof SyntaxError?'La ficha maestra no contiene un JSON válido.':(e as Error).message)}finally{setBusy(false)}
  }
  async function retry(){
    setBusy(true);setError('');
    try{const result=await api('/ai/jobs/'+job.job_id+'/retry',{method:'POST',headers:headers()});setJob(result);setPollVersion(v=>v+1);await refreshHistory()}
    catch(e){setError((e as Error).message)}finally{setBusy(false)}
  }
  async function openJob(id:string){setBusy(true);setError('');try{setJob(await api('/ai/jobs/'+id,{headers:headers()}));setPollVersion(v=>v+1)}catch(e){setError((e as Error).message)}finally{setBusy(false)}}
  return <section className="ai-workspace">
    <section className="panel"><h3>Imágenes → CORRECTOR → nueva prueba</h3>
      <p>Una solicitud por alumno con sus páginas y la misma ficha maestra. Las propuestas se cargan automáticamente en una prueba nueva y conservan transcripción, evidencias y puntos por componente.</p>
      {config?.simulated?<p className="demo-banner"><strong>MODO SIMULADO · SIN LLAMADAS A OPENAI</strong>Comprueba el flujo completo con notas y evidencias ficticias. El simulador no lee ni califica el contenido de las imágenes.</p>:<p className="tracking-note">{config?.ready?'OpenAI preparado. Las imágenes se envían al iniciar la corrección.':'El servicio OpenAI todavía no está configurado en el servidor.'}</p>}
      {config?.access_required&&<label>Código de acceso a la corrección IA<input type="password" autoComplete="off" value={token} onChange={e=>setToken(e.target.value)}/></label>}
      {error&&<p className="error" role="alert">{error}</p>}
      {config?.simulated&&db.groups.some((g:any)=>g.group_id==='DEMO-GROUP')&&<button disabled={busy} onClick={()=>void demo()}>Cargar lote ficticio de 3 alumnos</button>}
    </section>
    <section className="panel"><h3>1. Plantilla y ficha maestra</h3>
      <label>Plantilla de cuestiones<select disabled={busy} value={aid} onChange={e=>void chooseSource(e.target.value)}><option value="">Seleccione</option>{db.assessments.map((a:any)=><option key={a.assessment_id} value={a.assessment_id}>{a.title}</option>)}</select></label>
      {source&&<>
        <div className="ai-meta"><AssessmentMetaFields groups={db.groups} value={meta} metadataOnly onChange={v=>{setMeta(v);requestId.current=null}}/></div>
        <p className="tracking-note">La plantilla fija cuestiones, saberes, criterios y máximos desde la matriz curricular. Complete solución de referencia, evidencias, pesos y reglas de crédito parcial antes de confirmar. Los pesos deben sumar el máximo de cada cuestión.</p>
        <label>Ficha maestra CORRECTOR · JSON<textarea className="exchange-json" disabled={busy} spellCheck={false} value={rubric} onChange={e=>{setRubric(e.target.value);invalidate()}}/></label>
      </>}
    </section>
    {source&&<section className="panel"><h3>2. Imágenes por alumno</h3>
      <div className="ai-image-input"><label>student_id<select disabled={busy} value={studentId} onChange={e=>setStudentId(e.target.value)}><option value="">Seleccione</option>{students.map((s:any)=><option key={s.student_id}>{s.student_id}</option>)}</select></label>
        <label>Imágenes del alumno · orden de páginas<input type="file" accept="image/jpeg,image/png,image/webp" multiple disabled={busy} onChange={e=>setImages(Array.from(e.target.files||[]))}/></label>
        <button disabled={busy||!studentId||!images.length} onClick={()=>void uploadImages()}>Añadir imágenes</button>
      </div>
      {images.length>0&&<p>{images.map(f=>f.name).join(' · ')}</p>}
      <details><summary>Usar un PDF conjunto y asignar páginas</summary><PdfUpload onProcessed={d=>{setPdf(d);void refreshDocuments()}}/>{pdf&&<StudentSegmentsView document={pdf} onUpdated={d=>{setPdf(d);void refreshDocuments();invalidate()}}/>}</details>
      <h4>Seleccionar documentos del lote</h4><p className="tracking-note">Elija un documento por alumno. Solo se enviarán las páginas asignadas a su student_id.</p>
      <div className="ai-document-list">{documents.map(doc=>{
        const ids=Array.from(new Set(doc.segments.map(s=>s.student_key).filter((id):id is string=>!!id)));
        return <article key={doc.document_id}><b>{doc.original_filename}</b>{ids.map(id=>{
          const known=students.some((s:any)=>s.student_id===id);const pages=doc.segments.filter(s=>s.student_key===id).reduce((n,s)=>n+s.end_page-s.start_page+1,0);
          return <label className="ai-choice" key={id}><input type="checkbox" disabled={busy||!known} checked={selected[id]===doc.document_id} onChange={e=>{setSelected(old=>{const next={...old};if(e.target.checked)next[id]=doc.document_id;else delete next[id];return next});invalidate()}}/>{id} · {pages} páginas{!known?' · asigne un student_id de este grupo':''}</label>
        })}{!ids.length&&<small>Páginas pendientes de asignación.</small>}</article>
      })}</div>
      <label className="confirm-overwrite"><input type="checkbox" disabled={busy} checked={confirmed} onChange={e=>setConfirmed(e.target.checked)}/>Confirmo la ficha maestra y la asignación de imágenes a cada alumno</label>
      <p className="tracking-note">{Object.keys(selected).length} alumnos seleccionados. Las propuestas quedarán pendientes de validación docente.</p>
      <button disabled={busy||!config?.ready||!confirmed||!Object.keys(selected).length||!meta.title?.trim()} onClick={()=>void start()}>{busy?'Procesando…':'Crear prueba y corregir'}</button>
    </section>}
    {job&&<section className="panel ai-job-result" aria-label="Estado del lote IA"><h3>{statusNames[job.status]} · {job.completed}/{job.total} alumnos</h3>
      <p>{db.assessments.find((a:any)=>a.assessment_id===job.assessment_id)?.title||job.assessment_id}{job.simulated?' · SIMULACIÓN':''}</p>
      <progress aria-label="Progreso del lote" value={job.completed} max={job.total}/>
      {job.error&&<p className="error">{job.error}</p>}
      <div className="table"><table><thead><tr><th>student_id</th><th>Estado</th><th>Propuesta /10</th><th>Incidencias</th></tr></thead><tbody>{job.students.map((s:any)=><tr key={s.student_id}><td>{s.student_id}</td><td>{s.status==='completed'?'Propuesta cargada':statusNames[s.status]}</td><td>{s.final_score??'—'}</td><td>{s.error||s.review_reasons.join(' · ')||'Pendiente de validación docente'}</td></tr>)}</tbody></table></div>
      <div className="form-actions"><button onClick={()=>openCorrection(job.assessment_id)}>Abrir nueva prueba para revisar</button>{job.retry_available&&<button className="secondary" disabled={busy} onClick={()=>void retry()}>Reintentar solo alumnos pendientes</button>}</div>
      {job.retry_available&&!job.simulated&&<p className="tracking-note">Un reintento tras un fallo de transporte puede generar otra solicitud facturada. Las correcciones terminadas se conservan.</p>}
    </section>}
    <section className="panel"><h3>Lotes recientes</h3><button className="secondary" disabled={busy} onClick={()=>void refreshHistory()}>Actualizar lotes</button>
      {history.map(j=><button className="ai-history" key={j.job_id} disabled={busy} onClick={()=>void openJob(j.job_id)}>{db.assessments.find((a:any)=>a.assessment_id===j.assessment_id)?.title||j.assessment_id} · {statusNames[j.status]} · {j.completed}/{j.total}</button>)}
    </section>
  </section>;
}

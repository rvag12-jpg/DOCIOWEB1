import {useState} from 'react';
import {AssessmentMetaFields,localToday} from './AssessmentForm';
import {requestDocio} from '../api';

export function AssessmentBuilder({db,post,reload}:{db:any;post:(path:string,data:any)=>Promise<boolean>;reload:()=>Promise<void>}) {
  const [meta,setMeta]=useState<any>({title:'',group_id:'',evaluation:'1ª',assessment_date:localToday(),assessment_type:'exam'});
  const [questions,setQuestions]=useState<any[]>([{question_id:'Q1',title:'',max_score:1,knowledge_ids:'',criteria:''}]);
  const [editing,setEditing]=useState<any>(null);
  const [saving,setSaving]=useState(false);
  const [message,setMessage]=useState('');
  const [error,setError]=useState('');
  const setQ=(i:number,k:string,v:any)=>setQuestions(questions.map((q,n)=>n===i?{...q,[k]:v}:q));
  const add=()=>{
    let next=questions.length+1;
    while(questions.some(q=>q.question_id===`Q${next}`))next++;
    setQuestions([...questions,{question_id:`Q${next}`,title:'',max_score:1,knowledge_ids:'',criteria:''}]);
  };
  const create=async(e:React.FormEvent)=>{
    e.preventDefault();setSaving(true);setMessage('');
    try{
      const success=await post('/docio/assessments',{...meta,questions:questions.map(q=>({...q,max_score:Number(q.max_score),knowledge_ids:q.knowledge_ids.split(',').map((x:string)=>x.trim()).filter(Boolean),criteria:q.criteria.split(',').map((x:string)=>x.trim()).filter(Boolean)}))});
      if(success)setMessage('Prueba creada.');
    }finally{setSaving(false)}
  };
  const saveMetadata=async(e:React.FormEvent)=>{
    e.preventDefault();setSaving(true);setError('');setMessage('');
    try{
      await requestDocio('/docio/assessments/'+encodeURIComponent(editing.assessment_id),{method:'PATCH',body:JSON.stringify({title:editing.title,evaluation:editing.evaluation,assessment_date:editing.assessment_date})});
      await reload();setEditing(null);setMessage('Fecha y evaluación actualizadas.');
    }catch(e:any){setError(e.message)}finally{setSaving(false)}
  };
  return <section className="panel"><h3>Pruebas registradas</h3>
    {message&&<p role="status" className="success-note">{message}</p>}{error&&<p role="alert" className="error">{error}</p>}
    {db.assessments.length?<div className="table"><table><thead><tr><th>Prueba</th><th>Grupo</th><th>Evaluación</th><th>Fecha</th><th>Cuestiones</th><th>Acción</th></tr></thead><tbody>
      {db.assessments.map((a:any)=><tr key={a.assessment_id}><td>{a.title}</td><td>{db.groups.find((g:any)=>g.group_id===a.group_id)?.name||a.group_id}</td><td>{a.evaluation}</td><td>{a.assessment_date||'—'}</td><td>{a.questions?.length||0}</td><td><button type="button" className="secondary" disabled={saving} onClick={()=>{setEditing({...a});setError('');setMessage('')}}>Editar fecha y evaluación</button></td></tr>)}
    </tbody></table></div>:<p>Sin pruebas registradas.</p>}
    {editing&&<form className="metadata-editor" onSubmit={saveMetadata}><h4>Editar prueba · {editing.assessment_id}</h4>
      <AssessmentMetaFields groups={db.groups} value={editing} onChange={setEditing} metadataOnly/>
      <div className="form-actions"><button disabled={saving}>Guardar cambios</button><button type="button" className="secondary" disabled={saving} onClick={()=>setEditing(null)}>Cancelar</button></div>
    </form>}
    <h3>Nueva prueba</h3><form onSubmit={create}>
      <AssessmentMetaFields groups={db.groups} value={meta} onChange={setMeta}/>
      {questions.map((q,i)=><fieldset className="question-edit" key={q.question_id}><legend>{q.question_id}</legend>
        <input value={q.title} placeholder="Enunciado / título" required onChange={e=>setQ(i,'title',e.target.value)}/>
        <input type="number" min="0.01" step="0.01" required value={q.max_score} onChange={e=>setQ(i,'max_score',e.target.value)}/>
        <input value={q.knowledge_ids} placeholder="IDs de saberes, separados por coma" required onChange={e=>setQ(i,'knowledge_ids',e.target.value)}/>
        <input value={q.criteria} placeholder={meta.assessment_type==='project'?'Criterios (máx. 3)':'Criterios (máx. 2)'} required onChange={e=>setQ(i,'criteria',e.target.value)}/>
        {questions.length>1&&<button type="button" className="danger-lite" onClick={()=>setQuestions(questions.filter((_,n)=>n!==i))}>Quitar</button>}
      </fieldset>)}
      <div className="form-actions"><button type="button" className="secondary" disabled={saving} onClick={add}>+ Cuestión</button><button disabled={saving}>Crear prueba</button></div>
    </form>
  </section>;
}

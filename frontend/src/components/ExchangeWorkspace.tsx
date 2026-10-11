import {useState} from 'react';
import {requestDocio as api} from '../api';

type Assessment = {assessment_id:string; title:string};
type Change = {assessment_id:string; student_id:string; title:string; action:string; validated:boolean; final_score:number; previous_score:number|null};
type Preview = {total:number; importable:number; skipped:unknown[]; changes:Change[]; revision:string; replacements:number};
const actions:Record<string,string> = {create:'Crear', update:'Actualizar borrador', replace_validated:'Sustituir validada', skipped:'Conservar validada'};

export function ExchangeWorkspace({assessments,reload,demo}:{assessments:Assessment[];reload:()=>void|Promise<unknown>;demo:boolean}) {
  const [text,setText] = useState('');
  const [overwrite,setOverwrite] = useState(false);
  const [preview,setPreview] = useState<Preview|null>(null);
  const [busy,setBusy] = useState(false);
  const [error,setError] = useState('');
  const [result,setResult] = useState('');
  const [aid,setAid] = useState('');
  function edit(value:string) {setText(value);setPreview(null);setResult('');setError('');setOverwrite(false)}
  function payload() {
    const value = JSON.parse(text);
    if (!value || typeof value !== 'object' || Array.isArray(value)) throw new Error('El JSON debe contener un objeto DOCIO_CORRECTION_V1.');
    return {...value, overwrite, expected_revision:undefined};
  }
  async function readFile(file?:File) {
    if (!file) return;
    setPreview(null);setResult('');setError('');
    if (file.size>5*1024*1024) {setError('El JSON supera 5 MB. Divida las correcciones en lotes más pequeños.');return}
    setBusy(true);
    try {edit(await file.text())} catch {setError('No se pudo leer el archivo JSON.')} finally {setBusy(false)}
  }
  async function review() {
    setBusy(true);setError('');setResult('');setPreview(null);
    try {setPreview(await api('/docio/import/preview',{method:'POST',body:JSON.stringify(payload())}))}
    catch (e) {setError(e instanceof SyntaxError?'JSON no válido. Compruebe comillas, comas y llaves.':(e as Error).message)}
    finally {setBusy(false)}
  }
  async function commit() {
    if (!preview) return;
    setBusy(true);setError('');
    try {
      const response = await api('/docio/import',{method:'POST',body:JSON.stringify({...payload(),expected_revision:preview.revision})});
      setPreview(null);
      setResult(`Importación completada: ${response.imported} correcciones guardadas; ${response.skipped.length} validadas conservadas.`);
      await reload();
    } catch (e) {setError((e as Error).message);setPreview(null)} finally {setBusy(false)}
  }
  async function download() {
    setBusy(true);setError('');
    try {
      const data = await api('/docio/export/'+encodeURIComponent(aid));
      const url = URL.createObjectURL(new Blob([JSON.stringify(data,null,2)],{type:'application/json'}));
      const link = document.createElement('a');
      link.href=url;link.download=`DOCIO_${aid.replace(/[^a-zA-Z0-9_-]/g,'_')}.json`;link.click();
      setTimeout(()=>URL.revokeObjectURL(url),1000);
    } catch (e) {setError((e as Error).message)} finally {setBusy(false)}
  }
  function example() {
    edit(JSON.stringify({format:'DOCIO_CORRECTION_V1',assessment_id:'DEMO-FOLLOWUP',corrections:[
      {student_id:'DEMO-001',scores:{Q1:1.6,Q2:1.4},validated:true,comment:'Ejemplo completamente ficticio.'},
      {student_id:'DEMO-003',scores:{Q1:1.2,Q2:1.4},validated:true,evidence:[{criterion_id:'DEMO-C1',text:'Evidencia observable simulada.'}],comment:'Ejemplo completamente ficticio.'}
    ]},null,2));
  }
  return <section className="panel exchange-workspace">
    <h3>Importar y exportar correcciones</h3>
    <p className="tracking-note">Revise el lote antes de guardarlo. Cada corrección se identifica por la prueba y el <code>student_id</code>. Las puntuaciones deben respetar el máximo de cada cuestión.</p>
    {error&&<p className="error" role="alert">{error}</p>}
    {result&&<p className="success-note" role="status">{result}</p>}
    <div className="exchange-input">
      <label>Archivo JSON<input type="file" accept=".json,application/json" disabled={busy} onChange={e=>void readFile(e.target.files?.[0])}/></label>
      {demo&&<button className="secondary" disabled={busy} onClick={example}>Cargar ejemplo ficticio</button>}
    </div>
    <label>Contenido DOCIO_CORRECTION_V1<textarea className="exchange-json" spellCheck={false} disabled={busy} value={text} onChange={e=>edit(e.target.value)} placeholder="Pegue aquí el JSON de las correcciones"/></label>
    <label className="confirm-overwrite"><input type="checkbox" disabled={busy} checked={overwrite} onChange={e=>{setOverwrite(e.target.checked);setPreview(null);setResult('')}}/>Permitir la sustitución de correcciones ya validadas</label>
    <div className="form-actions"><button disabled={busy||!text.trim()} onClick={()=>void review()}>{busy?'Procesando…':'Revisar lote'}</button></div>
    {preview&&<section className="import-preview" aria-label="Vista previa de importación">
      <h4>Vista previa · {preview.total} correcciones</h4>
      <p>{preview.importable} se guardarán · {preview.skipped.length} validadas se conservarán.</p>
      {preview.replacements>0&&<p className="error">Se sustituirán {preview.replacements} correcciones validadas. Revise las puntuaciones antes de importar.</p>}
      <div className="table"><table><thead><tr><th>student_id</th><th>Prueba</th><th>Acción</th><th>Anterior /10</th><th>Propuesta /10</th><th>Estado propuesto</th></tr></thead><tbody>{preview.changes.map(c=><tr key={c.assessment_id+'::'+c.student_id}><td>{c.student_id}</td><td>{c.title}</td><td>{actions[c.action]}</td><td>{c.previous_score??'—'}</td><td>{c.final_score}</td><td>{c.validated?'Validada':'Borrador'}</td></tr>)}</tbody></table></div>
      <button disabled={busy||!preview.importable} onClick={()=>void commit()}>Importar {preview.importable} correcciones</button>
    </section>}
    <section className="exchange-export"><h4>Exportar una prueba</h4><p className="tracking-note">El archivo incluye cuestiones, evidencias, puntuaciones y estado de validación.</p>
      <label>Prueba para exportar<select disabled={busy} value={aid} onChange={e=>setAid(e.target.value)}><option value="">Seleccione</option>{assessments.map(a=><option key={a.assessment_id} value={a.assessment_id}>{a.title}</option>)}</select></label>
      <button disabled={busy||!aid} onClick={()=>void download()}>Descargar JSON</button>
    </section>
  </section>;
}

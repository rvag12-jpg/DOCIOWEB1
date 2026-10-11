export function AIReview({report}:{report:any}){
  if(!report)return null;
  return <section className="ai-review">
    <h4>{report.simulated?'SIMULACIÓN · puntuaciones ficticias':'Propuesta de CORRECTOR mediante IA'}</h4>
    <p>{report.teacher_validated?'Revisada y validada por el docente.':'Borrador pendiente de revisión docente.'} · {report.model}</p>
    {report.review_reasons?.length>0&&<div className="error"><b>Incidencias de la propuesta</b><ul>{report.review_reasons.map((reason:string,i:number)=><li key={i}>{reason}</li>)}</ul></div>}
    {report.result.items.map((item:any)=><details key={item.question_id}><summary>{item.question_id} · {item.legibility} · confianza declarada {Math.round(item.confidence*100)} %</summary>
      <h5>Transcripción de la respuesta</h5><p className="ai-transcription">{item.transcription}</p>
      <div className="table"><table><thead><tr><th>Componente</th><th>Puntos</th><th>Evidencia y justificación</th></tr></thead><tbody>{item.components.map((c:any)=><tr key={c.component_id}><td>{c.component_id}</td><td>{c.awarded??'Pendiente'}</td><td>{c.observed_evidence.join(' · ')}<br/>{c.justification}</td></tr>)}</tbody></table></div>
      {item.errors.length>0&&<><h5>Errores observados</h5><ul>{item.errors.map((error:string,i:number)=><li key={i}>{error}</li>)}</ul></>}
      <p>{item.feedback}</p><small>Páginas de referencia: {item.page_numbers.join(', ')}</small>
    </details>)}
    <small>La confianza del modelo no sustituye la comprobación de la lectura y de la rúbrica.</small>
  </section>;
}

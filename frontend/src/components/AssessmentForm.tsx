const evaluations = ['Inicial', '1ª', '2ª', 'Ordinaria'];
export function localToday() {
  const now = new Date();
  return `${now.getFullYear()}-${String(now.getMonth()+1).padStart(2,'0')}-${String(now.getDate()).padStart(2,'0')}`;
}
export function AssessmentMetaFields({groups,value,onChange,metadataOnly=false}: {
  groups:any[]; value:any; onChange:(v:any)=>void; metadataOnly?:boolean;
}) {
  const set = (key:string, next:any) => onChange({...value,[key]:next});
  return <>
    <label>Título<input required value={value.title || ''} onChange={e=>set('title',e.target.value)}/></label>
    {!metadataOnly && <label>Grupo<select required value={value.group_id || ''} onChange={e=>set('group_id',e.target.value)}>
      <option value="">Seleccione</option>{groups.map(g=><option key={g.group_id} value={g.group_id}>{g.name} · {g.course}</option>)}</select></label>}
    <label>Evaluación<select required value={value.evaluation || ''} onChange={e=>set('evaluation',e.target.value)}>
      <option value="" disabled>Seleccione</option>{evaluations.map(x=><option key={x}>{x}</option>)}</select></label>
    <label>Fecha<input type="date" required value={value.assessment_date || ''} onChange={e=>set('assessment_date',e.target.value)}/></label>
    {!metadataOnly && <label>Tipo<select value={value.assessment_type || 'exam'} onChange={e=>set('assessment_type',e.target.value)}>
      <option value="exam">Prueba</option><option value="activity">Actividad</option><option value="project">Proyecto</option></select></label>}
  </>;
}

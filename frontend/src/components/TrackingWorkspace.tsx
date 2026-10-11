import {useEffect, useState} from 'react';
import {CriterionRadar} from './CriterionRadar';
import {requestDocio} from '../api';

const evaluations = ['', 'Inicial', '1ª', '2ª', 'Ordinaria'];
const statusLabels: Record<string, string> = {
  no_evidence: 'Sin evidencias validadas', partial: 'Evidencias incompletas',
  pending: 'Con criterios pendientes', achieved: 'Criterios observados superados',
};

export function TrackingWorkspace({db}: {db: any}) {
  const [group, setGroup] = useState('');
  const [evaluation, setEvaluation] = useState('');
  const [data, setData] = useState<any>(null);
  const [selected, setSelected] = useState('');
  const [profile, setProfile] = useState<any>(null);
  const [loading, setLoading] = useState(false);
  const [profileLoading, setProfileLoading] = useState(false);
  const [error, setError] = useState('');

  useEffect(() => {
    const controller = new AbortController();
    setData(null);
    setError('');
    if (!group) { setLoading(false); return () => controller.abort(); }
    setLoading(true);
    const query = evaluation ? '?evaluation=' + encodeURIComponent(evaluation) : '';
    void requestDocio('/docio/group-overview/' + encodeURIComponent(group) + query,
      {signal: controller.signal})
      .then(result => { if (!controller.signal.aborted) setData(result); })
      .catch(e => { if (!controller.signal.aborted) setError(e.message); })
      .finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [group, evaluation, db]);

  useEffect(() => {
    const controller = new AbortController();
    setProfile(null);
    if (!selected) { setProfileLoading(false); return () => controller.abort(); }
    setProfileLoading(true);
    setError('');
    const query = evaluation ? '?evaluation=' + encodeURIComponent(evaluation) : '';
    void requestDocio('/docio/student-profile/' + encodeURIComponent(selected) + query,
      {signal: controller.signal})
      .then(result => { if (!controller.signal.aborted) setProfile(result); })
      .catch(e => { if (!controller.signal.aborted) setError(e.message); })
      .finally(() => { if (!controller.signal.aborted) setProfileLoading(false); });
    return () => controller.abort();
  }, [selected, evaluation, db]);

  const current = data?.students.find((s: any) => s.student_id === selected);
  return <section className="panel">
    <h3>Seguimiento criterial</h3>
    <div className="tracking-filters">
      <label>Grupo<select value={group} onChange={e => {
        setGroup(e.target.value); setSelected(''); setProfile(null);
      }}><option value="">Seleccione</option>{db.groups.map((g: any) =>
        <option key={g.group_id} value={g.group_id}>{g.name} · {g.course}</option>
      )}</select></label>
      <label>Evaluación<select value={evaluation} onChange={e => {
        setEvaluation(e.target.value); setSelected(''); setProfile(null);
      }}>{evaluations.map(x => <option key={x} value={x}>{x || 'Todas'}</option>)}</select></label>
    </div>
    <p className="tracking-note">Se utilizan correcciones validadas. El nivel de cada criterio corresponde a su última evidencia, ordenada por fecha. La media de pruebas es descriptiva.</p>
    {error && <p className="error" role="alert">{error}</p>}
    {loading && <p role="status">Cargando seguimiento…</p>}
    {!group && <p>Selecciona un grupo para consultar su evolución.</p>}
    {data && <>
      <div className="tracking-summary"><b>{data.students.length} alumnos</b><span>{data.assessments.length} pruebas en el filtro</span></div>
      {!data.assessments.length && <p>No hay pruebas en esta evaluación.</p>}
      {!data.students.length && <p>El grupo todavía no tiene alumnado registrado.</p>}
      <div className="heatmap">{data.students.map((s: any) => <button type="button"
        key={s.student_id} className={'heat ' + (s.status === 'achieved' ? 'done' : s.status === 'pending' ? 'pending' : 'unobserved')}
        aria-pressed={selected === s.student_id} onClick={() => setSelected(s.student_id)}>
        <b>{s.student_id}</b><span>{s.mean == null ? '—' : s.mean + '/10'}</span>
        <small>{statusLabels[s.status]}</small>
        <small>{s.assessments} pruebas validadas · {s.pending_criteria.length} criterios pendientes</small>
        {!!s.missing_criteria.length && <small>{s.missing_criteria.length} criterios sin evidencia</small>}
        {!!s.drafts && <small>{s.drafts} borradores</small>}
      </button>)}</div>
    </>}
    {selected && <div className="longitudinal-card">
      <div className="student-head"><div><small>FICHA LONGITUDINAL · {evaluation || 'TODAS LAS EVALUACIONES'}</small><h3>{selected}</h3></div>
        <button className="danger-lite" onClick={() => {setSelected(''); setProfile(null);}}>Cerrar</button></div>
      {profileLoading && <p role="status">Cargando ficha…</p>}
      {profile && <>
        <div className="cards"><article><strong>{profile.mean ?? '—'}</strong><p>Media de pruebas /10</p></article>
          <article><strong>{profile.attempts.length}</strong><p>Pruebas validadas</p></article>
          <article><strong>{Object.keys(profile.criteria).length}</strong><p>Criterios con evidencia</p></article></div>
        {!profile.attempts.length && <p>Sin correcciones validadas en esta evaluación.</p>}
        {!!profile.attempts.length && <><h4>Evolución por pruebas</h4><div className="timeline">{profile.attempts.map((a: any) =>
          <div className="timeline-item" key={a.assessment_id}><b>{a.date || 'Sin fecha'} · {a.evaluation}</b><span>{a.title}</span><strong>{a.final_score}/10</strong></div>
        )}</div></>}
        <h4>Último nivel por criterio · comparación con el grupo</h4>
        <CriterionRadar student={Object.fromEntries(Object.entries(profile.criteria).map(([cid, items]: any) => [cid, items.at(-1).score]))} mean={data?.criterion_means || {}}/>
        {!!current?.missing_criteria.length && <p>Sin evidencia: {current.missing_criteria.join(' · ')}</p>}
        <div className="criterion-history">{Object.entries(profile.criteria).map(([cid, items]: any) =>
          <div className="criterion-history-row" key={cid}><b>{cid}</b>{items.map((x: any) =>
            <span className={x.score >= 5 ? 'achieved' : 'pending'} key={x.assessment_id}>{x.date || 'Sin fecha'} · {x.evaluation} · {x.score}</span>
          )}</div>
        )}</div>
      </>}
    </div>}
  </section>;
}

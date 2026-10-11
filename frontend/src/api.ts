import type{DocumentView,SegmentRange}from'./types';const CHUNK=256*1024;function detail(v:unknown):string{if(typeof v==='string')return v;if(Array.isArray(v))return v.map(detail).join('; ');if(v&&typeof v==='object'){const x=v as Record<string,unknown>;return typeof x.msg==='string'?x.msg:JSON.stringify(v)}return String(v??'Error desconocido')}async function json<T>(r:Response):Promise<T>{const p=await r.json().catch(()=>null) as (T&{detail?:unknown})|null;if(!r.ok||!p)throw new Error(p?.detail!==undefined?detail(p.detail):`Error HTTP ${r.status}`);return p}function send(url:string,b:Blob,i:number,n:number){return new Promise<void>((ok,no)=>{const x=new XMLHttpRequest();x.open('POST',url);x.timeout=120000;x.setRequestHeader('Content-Type','application/octet-stream');x.onload=()=>x.status>=200&&x.status<300?ok():no(new Error(`fragmento ${i+1}/${n}: HTTP ${x.status}`));x.onerror=()=>no(new Error(`fragmento ${i+1}/${n}: error de red`));x.ontimeout=()=>no(new Error(`fragmento ${i+1}/${n}: timeout`));x.send(b)})}export async function uploadDocument(file:File,pps?:number):Promise<DocumentView>{if(file.size>100*1024*1024)throw new Error('El PDF supera 100 MB');const init=await fetch('/api/v1/documents/chunked/init',{method:'POST'});const{upload_id}=await json<{upload_id:string}>(init);const n=Math.ceil(file.size/CHUNK);for(let i=0;i<n;i++)await send(`/api/v1/documents/chunked/${upload_id}/part/${i}`,file.slice(i*CHUNK,Math.min((i+1)*CHUNK,file.size)),i,n);return json<DocumentView>(await fetch(`/api/v1/documents/chunked/${upload_id}/complete`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({filename:file.name,size:file.size,chunks:n,pages_per_student:pps??null})}))}export async function updateSegments(id:string,ranges:SegmentRange[]):Promise<DocumentView>{return json<DocumentView>(await fetch(`/api/v1/documents/${id}/segments`,{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify({ranges})}))}

export async function requestDocio(path:string, options:RequestInit={}):Promise<any>{
  const headers=new Headers(options.headers);
  if(options.body && !headers.has('Content-Type'))headers.set('Content-Type','application/json');
  const response=await fetch('/api/v1'+path,{...options,headers});
  const body=await response.text();
  let payload:any;
  try{payload=body?JSON.parse(body):null}catch{payload=null}
  if(!response.ok)throw new Error(payload?.detail!==undefined?detail(payload.detail):(body||`Error HTTP ${response.status}`));
  if(payload===null)throw new Error(`Respuesta no válida del servidor (HTTP ${response.status})`);
  return payload;
}

export async function uploadStudentImages(files:File[],studentId:string):Promise<DocumentView>{
  if(!files.length||files.length>12)throw new Error('Seleccione entre 1 y 12 imágenes para el alumno');
  for(const file of files)if(!file.size||file.size>20*1024*1024)throw new Error('Cada imagen debe ocupar entre 1 byte y 20 MB');
  let document:DocumentView|undefined;
  for(const file of files){
    const{upload_id}=await requestDocio('/documents/chunked/init',{method:'POST'});
    const chunks=Math.ceil(file.size/CHUNK);
    for(let i=0;i<chunks;i++)await send(`/api/v1/documents/chunked/${upload_id}/part/${i}`,file.slice(i*CHUNK,Math.min((i+1)*CHUNK,file.size)),i,chunks);
    document=await requestDocio(`/documents/chunked/${upload_id}/image-complete`,{method:'POST',body:JSON.stringify({student_id:studentId,document_id:document?.document_id,filename:file.name,size:file.size,chunks})});
  }
  return document!;
}

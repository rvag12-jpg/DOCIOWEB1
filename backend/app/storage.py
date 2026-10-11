import json,shutil
from pathlib import Path
from uuid import uuid4
from fastapi import UploadFile
from app.core.config import settings
from app.models import DocumentView
class UploadTooLargeError(ValueError): pass
class DocumentStore:
 def __init__(self,root:Path=settings.data_dir): self.root=root; self.root.mkdir(parents=True,exist_ok=True)
 def create(self):
  i=uuid4().hex; d=self.root/i; (d/'pages').mkdir(parents=True); return i,d
 def document_dir(self,i):
  if not i.isalnum(): raise FileNotFoundError(i)
  return self.root/i
 def remove(self,i): shutil.rmtree(self.document_dir(i),ignore_errors=True)
 async def save_upload(self,u:UploadFile,d:Path):
  limit=settings.max_upload_mb*1024*1024; written=0
  with d.open('wb') as f:
   while chunk:=await u.read(1024*1024):
    written+=len(chunk)
    if written>limit: raise UploadTooLargeError(f'El PDF supera el límite de {settings.max_upload_mb} MB')
    f.write(chunk)
 def save_manifest(self,doc:DocumentView): (self.document_dir(doc.document_id)/'manifest.json').write_text(json.dumps(doc.model_dump(mode='json'),ensure_ascii=False,indent=2),encoding='utf-8')
 def load_manifest(self,i):
  p=self.document_dir(i)/'manifest.json'
  if not p.exists(): raise FileNotFoundError(i)
  return DocumentView.model_validate_json(p.read_text(encoding='utf-8'))
store=DocumentStore()

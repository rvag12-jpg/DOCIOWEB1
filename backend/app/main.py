from pathlib import Path
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from app.api.documents import router as documents_router
from app.api.docio import router as docio_router
from app.api.tracking import router as tracking_router
from app.core.config import settings
app=FastAPI(title='DOCIOWEB1',version='0.10.0')
app.add_middleware(CORSMiddleware,allow_origins=list(settings.cors_origins),allow_credentials=True,allow_methods=['*'],allow_headers=['*'])
app.include_router(documents_router,prefix=settings.api_prefix)
app.include_router(docio_router,prefix=settings.api_prefix)
app.include_router(tracking_router,prefix=settings.api_prefix)
settings.data_dir.mkdir(parents=True,exist_ok=True)
app.mount('/media',StaticFiles(directory=settings.data_dir),name='media')
@app.get('/health')
def health(): return {'status':'ok','app':'DOCIOWEB1','version':'0.10.0'}
frontend=Path('/app/frontend_dist')
if frontend.exists():
 assets=frontend/'assets'
 if assets.exists(): app.mount('/assets',StaticFiles(directory=assets),name='assets')
 @app.get('/{path:path}',include_in_schema=False)
 def spa(path:str):
  candidate=frontend/path
  if path and candidate.is_file(): return FileResponse(candidate)
  return FileResponse(frontend/'index.html')

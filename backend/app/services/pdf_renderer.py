from pathlib import Path
from pdf2image import convert_from_path,pdfinfo_from_path
class PdfRenderingError(RuntimeError): pass
def render_pdf(pdf_path:Path,output_dir:Path,dpi:int)->list[Path]:
    output_dir.mkdir(parents=True,exist_ok=True)
    try: page_count=int(pdfinfo_from_path(pdf_path).get('Pages',0))
    except Exception as exc: raise PdfRenderingError(f'No se pudo leer la información del PDF: {exc}') from exc
    if page_count<1: raise PdfRenderingError('El PDF no contiene páginas renderizables')
    paths=[]
    for n in range(1,page_count+1):
        try:
            images=convert_from_path(pdf_path,dpi=dpi,first_page=n,last_page=n,fmt='jpeg',thread_count=1,grayscale=True,jpegopt={'quality':85,'optimize':True})
            if not images: raise PdfRenderingError(f'No se pudo renderizar la página {n}')
            image=images[0]; path=output_dir/f'page-{n:04d}.jpg'; image.save(path,'JPEG',quality=85,optimize=True); image.close(); images.clear(); paths.append(path)
        except PdfRenderingError: raise
        except Exception as exc: raise PdfRenderingError(f'Error al renderizar la página {n}: {exc}') from exc
    return paths

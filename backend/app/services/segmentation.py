from app.models import PageView,SegmentRange,StudentSegment
class SegmentationError(ValueError): pass
def pending_segment(pages):
    return [] if not pages else [StudentSegment(label='Lote pendiente de segmentar',start_page=pages[0].page_number,end_page=pages[-1].page_number,pages=pages)]
def fixed_size_segments(pages:list[PageView],size:int):
    if size<1: raise SegmentationError('pages_per_student debe ser mayor que cero')
    out=[]
    for i,o in enumerate(range(0,len(pages),size),1):
        g=pages[o:o+size]; out.append(StudentSegment(student_key=f'PROVISIONAL-{i:03d}',label=f'Alumno provisional {i}',start_page=g[0].page_number,end_page=g[-1].page_number,pages=g))
    return out
def manual_segments(pages:list[PageView],ranges:list[SegmentRange]):
    by={p.page_number:p for p in pages}; used=set(); out=[]
    for i,r in enumerate(sorted(ranges,key=lambda x:x.start_page),1):
        nums=set(range(r.start_page,r.end_page+1))
        if nums-set(by): raise SegmentationError('Rango fuera del documento')
        if nums&used: raise SegmentationError('Hay páginas asignadas más de una vez')
        used|=nums; key=r.student_key or f'MANUAL-{i:03d}'; out.append(StudentSegment(student_key=key,label=r.label or key,start_page=r.start_page,end_page=r.end_page,pages=[by[n] for n in sorted(nums)]))
    for n in sorted(set(by)-used): out.append(StudentSegment(label='Sin asignar',start_page=n,end_page=n,pages=[by[n]]))
    return sorted(out,key=lambda x:x.start_page)

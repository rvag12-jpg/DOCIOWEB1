from datetime import datetime, timezone
from pydantic import BaseModel, Field, model_validator
class PageView(BaseModel):
    page_number:int=Field(ge=1); image_url:str
class StudentSegment(BaseModel):
    student_key:str|None=None; label:str; start_page:int=Field(ge=1); end_page:int=Field(ge=1); pages:list[PageView]
class DocumentView(BaseModel):
    document_id:str; original_filename:str; created_at:datetime=Field(default_factory=lambda:datetime.now(timezone.utc)); page_count:int; pages:list[PageView]; segments:list[StudentSegment]
class SegmentRange(BaseModel):
    student_key:str|None=None; label:str|None=None; start_page:int=Field(ge=1); end_page:int=Field(ge=1)
    @model_validator(mode='after')
    def order(self):
        if self.end_page<self.start_page: raise ValueError('end_page no puede ser menor que start_page')
        return self
class SegmentUpdate(BaseModel): ranges:list[SegmentRange]=Field(min_length=1)

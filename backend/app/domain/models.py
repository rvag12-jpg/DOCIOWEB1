from dataclasses import dataclass, field
from datetime import date
from typing import Literal

EvaluationPeriod = Literal["initial", "first", "second", "ordinary"]


@dataclass(slots=True)
class Student:
    student_id: str
    display_name: str | None = None
    active: bool = True


@dataclass(slots=True)
class Group:
    group_id: str
    name: str
    academic_year: str
    student_ids: list[str] = field(default_factory=list)


@dataclass(slots=True)
class Criterion:
    criterion_id: str
    code: str
    title: str


@dataclass(slots=True)
class BasicKnowledge:
    knowledge_id: str
    code: str
    title: str
    criterion_ids: list[str] = field(default_factory=list)


@dataclass(slots=True)
class Question:
    question_id: str
    number: int
    title: str
    knowledge_ids: list[str] = field(default_factory=list)
    criterion_ids: list[str] = field(default_factory=list)
    max_score: float | None = None


@dataclass(slots=True)
class Assessment:
    assessment_id: str
    title: str
    group_id: str
    evaluation: EvaluationPeriod
    assessment_date: date | None = None
    questions: list[Question] = field(default_factory=list)


@dataclass(slots=True)
class Evidence:
    evidence_id: str
    criterion_id: str
    text: str
    score: float | None = None


@dataclass(slots=True)
class Correction:
    assessment_id: str
    student_id: str
    evidence: list[Evidence] = field(default_factory=list)
    final_score: float | None = None
    validated: bool = False

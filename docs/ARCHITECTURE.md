# Arquitectura DOCIOWEB1

## Principios

DOCIOWEB1 separa dominio docente, persistencia, API y presentación. El bloque de procesamiento documental se considera un subsistema de entrada y no el núcleo del dominio.

## Dominio

Entidades principales:

- `Group`: grupo docente.
- `Student`: alumno; clave estable `student_id`.
- `Assessment`: prueba/evidencia evaluable.
- `Question`: cuestión de una prueba.
- `BasicKnowledge`: saber básico.
- `Criterion`: criterio de evaluación.
- `Evidence`: evidencia observable de corrección.
- `Correction`: corrección de una cuestión para un alumno.
- `CriterionResult`: resultado agregado por criterio.

Relaciones esenciales:

```text
Group 1---N Student
Assessment 1---N Question
Question N---N BasicKnowledge
BasicKnowledge N---N Criterion
Student N---N Assessment (Correction)
Correction 1---N Evidence
```

## Flujo DOCIO_CORRECTION_V1

```text
PDF / JSON
   ↓
Identificación de assessment
   ↓
student_id
   ↓
cuestiones
   ↓
saberes evaluados
   ↓
matriz saberes → criterios
   ↓
evidencias observables
   ↓
calificaciones y cierre/validación
   ↓
seguimiento e informes
```

La reconciliación de alumnos nunca depende del nombre.

## Subsistema PDF

El flujo heredado de DOCIOWEB se integrará como:

```text
subida fragmentada
→ reconstrucción del PDF
→ validación
→ renderizado página a página
→ segmentación
→ asignación a student_id
→ visualización
→ corrección
```

El renderizado debe mantener memoria acotada para funcionar en servicios con RAM limitada.

## API prevista

- `/api/v1/health`
- `/api/v1/groups`
- `/api/v1/students`
- `/api/v1/assessments`
- `/api/v1/corrections`
- `/api/v1/curriculum`
- `/api/v1/imports/docio-correction-v1`
- `/api/v1/documents/...`
- `/api/v1/reports/...`

## Frontend

Navegación principal:

```text
Inicio
Grupos
Alumnado
Pruebas
Corrección
Criterios
Seguimiento
Informes
Configuración
```

La digitalización PDF se presenta dentro del flujo de Pruebas/Corrección, no como aplicación separada.

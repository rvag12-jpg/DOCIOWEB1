# DOCIOWEB1

Aplicación web de evaluación criterial basada en DOCIO, con React/TypeScript y FastAPI. El alumnado se identifica exclusivamente mediante `student_id`.

## Funciones

- Grupos, alumnado, pruebas, correcciones y evidencias observables.
- Evaluaciones Inicial, 1.ª, 2.ª y Ordinaria, con fecha de cada prueba.
- Edición del título, fecha y evaluación de pruebas existentes, conservando sus cuestiones, grupo y correcciones; registro del cambio en el historial.
- Seguimiento del grupo y ficha longitudinal con el mismo filtro de evaluación.
- Última evidencia por criterio, comparación con la media del grupo y recuperación cronológica.
- Estados separados para criterios pendientes, evidencias incompletas y ausencia de evidencias. Los borradores no forman parte del seguimiento validado.
- Importación/exportación `DOCIO_CORRECTION_V1` y protección de correcciones validadas frente a sustitución sin confirmación.
- Subida fragmentada de PDF, renderizado de memoria acotada y segmentación por alumno.

La media de pruebas que aparece en Seguimiento es descriptiva; no representa una regla de calificación final del curso. La media criterial del grupo compara el último nivel observado de cada alumno dentro del filtro. Los criterios sin evidencia se muestran sin puntuación y no se convierten en ceros.

## Regla curricular

Primero se identifican los saberes básicos efectivamente evaluados. Los criterios se seleccionan exclusivamente desde la matriz saberes–criterios configurada: 1–2 por cuestión, hasta 3 en proyectos. No se infieren del enunciado.

## Estructura

| Ubicación | Función |
|---|---|
| `backend/app/api` | Documentos, evaluación y seguimiento |
| `backend/app/services/evaluation.py` | Cálculo común y orden cronológico |
| `backend/app/repository.py` | PostgreSQL o SQLite; historial de cambios |
| `backend/tests` | Regresiones con datos sintéticos aislados |
| `frontend/src/components` | Interfaz DOCIO, pruebas, ficha y seguimiento |
| `backend/Dockerfile` | Compilación del frontend y servicio web |
| `.github/workflows/ci.yml` | Pruebas, TypeScript y compilación Docker |

## Desarrollo y comprobación

```bash
python -m pip install -r backend/requirements-dev.txt
PYTHONPATH=backend python -m unittest discover -s backend/tests -v
npm --prefix frontend ci
npm --prefix frontend run build
```

Para servir la API localmente:

```bash
PYTHONPATH=backend python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

La imagen Docker sirve el frontend y la API desde un mismo origen y utiliza `PORT` (8000 por defecto).

## Persistencia

`DATABASE_URL` activa PostgreSQL. Sin ella, el repositorio utiliza SQLite en `DOCIO_DATA_DIR` (`data` por defecto). SQLite dentro del contenedor de Render no garantiza conservación de datos entre despliegues. Los PDF y sus imágenes también necesitan almacenamiento persistente; PostgreSQL conserva los registros de evaluación, no los archivos PDF.

La versión 0.11 añade seguimiento fiable, edición de metadatos y pruebas de regresión. El cambio a PostgreSQL y la migración de los registros existentes deben completarse antes de dar por garantizada la persistencia del servicio.

## Demostración con datos sintéticos (v0.12)

`DOCIO_DEMO_MODE=true` activa un grupo, tres alumnos `DEMO-001`–`DEMO-003`, dos pruebas y cuatro correcciones completamente inventados. Incluye ejemplos de recuperación, criterios pendientes y un borrador sin evidencias validadas. Los saberes y criterios DEMO son ficticios y no forman una matriz curricular oficial.

La demostración utiliza tablas `demo_records` y `demo_audit`, separadas de las tablas ordinarias, y una subcarpeta `demo` para sus archivos. No importa `docio.json` ni copia registros del modo ordinario. La interfaz muestra un aviso permanente de datos ficticios. Las inicializaciones posteriores conservan las ediciones ya realizadas en la demostración.

Las pruebas automáticas utilizan exclusivamente fixtures inventadas. GitHub Actions levanta PostgreSQL 18 para comprobar escrituras, historial y aislamiento en esquemas temporales; no conecta a la base de datos de Render.

La demostración publicada sin `DATABASE_URL` utiliza SQLite y puede reiniciar sus ejemplos al redeploy. El soporte PostgreSQL se valida en CI; conectar la base de datos del servicio principal sigue siendo una configuración independiente.

## Intercambio JSON (v0.13)

El módulo **Intercambio JSON** permite abrir un archivo o pegar un `DOCIO_CORRECTION_V1`, revisar las acciones y puntuaciones de cada alumno y guardar el lote. En DEMO incluye un botón para cargar un ejemplo completamente ficticio. También permite descargar todas las correcciones de una prueba, con cuestiones, evidencias y estado de validación.

La vista previa no modifica correcciones. Por defecto se conservan las ya validadas; su sustitución requiere activar la opción correspondiente y revisar de nuevo el lote. Si los registros cambian después de la vista previa, la importación se rechaza hasta revisarlos otra vez. El lote se valida y escribe en una sola transacción, incluido su historial; un error revierte todo el lote tanto en SQLite como en PostgreSQL.

Se comprueban identificadores, pertenencia al grupo, cuestiones y criterios de la prueba, puntuaciones finitas dentro de sus máximos y duplicados de prueba–alumno. Una corrección validada requiere puntuar todas las cuestiones; un borrador puede estar incompleto. Las puntuaciones finales se recalculan desde las cuestiones, sin confiar en una nota final incluida en el JSON. Se admiten los alias `students` y `evidences` del intercambio anterior.

API: `POST /api/v1/docio/import/preview`, `POST /api/v1/docio/import` y `GET /api/v1/docio/export/{assessment_id}`. La interfaz envía `expected_revision` al confirmar para comprobar que la vista previa sigue vigente. Los clientes antiguos pueden seguir importando sin este campo, con la validación y transacción del lote.

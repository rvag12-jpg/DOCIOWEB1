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

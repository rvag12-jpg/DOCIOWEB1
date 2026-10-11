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
- Imágenes JPEG/PNG/WebP por alumno, corrección mediante Responses API o simulador y carga automática de propuestas en una prueba nueva.
- Ficha maestra CORRECTOR confirmada, desglose por componentes, revisión de lectura y validación docente.

La media de pruebas que aparece en Seguimiento es descriptiva; no representa una regla de calificación final del curso. La media criterial del grupo compara el último nivel observado de cada alumno dentro del filtro. Los criterios sin evidencia se muestran sin puntuación y no se convierten en ceros.

## Regla curricular

Primero se identifican los saberes básicos efectivamente evaluados. Los criterios se seleccionan exclusivamente desde la matriz saberes–criterios configurada: 1–2 por cuestión, hasta 3 en proyectos. No se infieren del enunciado.

## Estructura

| Ubicación | Función |
|---|---|
| `backend/app/api` | Documentos, evaluación, seguimiento y lotes IA |
| `backend/app/services/corrector.py` | Marco CORRECTOR y comprobación de resultados |
| `backend/app/services/ai_provider.py` | OpenAI Responses API y simulador sin red |
| `backend/app/services/ai_jobs.py` | Cola y guardado atómico por alumno |
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

## Corrección de imágenes (v0.14)

El módulo **Corrección IA** implementa el recorrido completo: documentos asignados por `student_id`, ficha maestra, una solicitud por alumno y una prueba nueva con correcciones en borrador. Usa OpenAI Responses API; las solicitudes de API no crean conversaciones en la interfaz de ChatGPT.

1. Seleccionar una prueba como plantilla de cuestiones, saberes, criterios y máximos.
2. Completar la ficha maestra JSON: materia, curso, duración, solución de referencia, evidencias esperadas, componentes y reglas de crédito parcial. La suma de componentes debe coincidir con el máximo de cada cuestión. Confirmar la ficha y la asignación de páginas.
3. Añadir hasta 12 imágenes por alumno (JPEG, PNG o WebP, hasta 20 MB cada una), o subir un PDF conjunto y asignar sus páginas a los identificadores registrados. Los archivos se suben fragmentados; las imágenes se orientan y convierten a JPEG sin metadatos, con un máximo de 3000 píxeles por lado.
4. Crear el lote. Se clona la plantilla en una prueba nueva y se guarda su ficha maestra confirmada. El servidor envía únicamente las páginas del alumno, su identificador y el marco de corrección; no añade otras calificaciones ni su historial.
5. Revisar las propuestas en **Corrección**: imágenes de origen, transcripción, páginas, legibilidad, confianza, evidencias, justificaciones y crédito por componente. Editar las puntuaciones y confirmar la revisión docente antes de validar.

El prompt adapta el marco CORRECTOR 2.0.3 y las reglas del corrector personal: cuestiones independientes, matriz saberes–criterios explícita, sin completar pasos ausentes ni descontar dos veces el mismo error. La API devuelve JSON estructurado; el servidor comprueba identidad, cuestiones, componentes, páginas y límites, y calcula la nota. Una lectura ilegible o incompleta requiere revisión y conserva la nota pendiente en vez de convertirla en cero. Evidencias y transcripciones equivalentes con créditos distintos se marcan para contraste, sin promediar las notas. Estas comprobaciones no garantizan la precisión de la lectura o del juicio científico del modelo.

La prueba original se conserva. Cada propuesta y el estado de su alumno se escriben juntos en una transacción; un fallo no deja un resultado cargado sin su registro de progreso. `request_id` evita crear otra prueba al reenviar la misma solicitud. Los errores se muestran por alumno y el reintento manual conserva las correcciones terminadas. Un lote en cola se reactiva al consultarlo tras un reinicio; una ejecución abandonada permite reintentar después de 10 minutos. Se comprueban hashes de las imágenes antes de enviarlas. No hay reintentos automáticos de OpenAI: un fallo de transporte puede haber generado una solicitud facturada.

Las propuestas no cuentan en las medias ni en el seguimiento hasta que se validan. El resultado original de IA se conserva junto a las ediciones docentes, y el historial registra los cambios. La importación JSON mantiene esta revisión; una simulación no puede validar una evaluación en modo ordinario.

### Clave ficticia y activación posterior

La demostración publicada utiliza **`DOCIO_AI_PROVIDER=mock`**, datos y notas completamente ficticios, y no llama a OpenAI. El botón **Cargar lote ficticio de 3 alumnos** prepara imágenes y una ficha inventadas; el simulador asigna un 65 % para comprobar el transporte y no lee el contenido. `.env.example` contiene únicamente marcadores de posición.

Para trabajar más adelante con una clave verdadera, configurar estas variables **en el servidor** (por ejemplo, en Environment del servicio Render):

| Variable | Configuración |
|---|---|
| `DOCIO_AI_PROVIDER` | `openai` |
| `OPENAI_API_KEY` | Clave verdadera con acceso al modelo |
| `DOCIO_AI_MODEL` | `gpt-6-astra` por defecto; modelo compatible con imágenes y JSON estructurado disponible en la cuenta |
| `DOCIO_AI_ACCESS_TOKEN` | Código aleatorio privado de al menos 24 caracteres |
| `DOCIO_AI_MAX_STUDENTS` | `40` por defecto |
| `DOCIO_AI_MAX_OUTPUT_TOKENS` | `16000` por defecto |

La aplicación no carga `.env.example` automáticamente. En local, exportar las variables en el proceso que inicia Uvicorn. La interfaz solicita únicamente el código de acceso del servicio IA y lo conserva en memoria durante esa sesión. No introducir `OPENAI_API_KEY` en el navegador, en variables `VITE_*` ni en el repositorio. Los valores ficticios de ejemplo no activan OpenAI.

Los endpoints de lotes requieren `Authorization: Bearer <DOCIO_AI_ACCESS_TOKEN>` en modo OpenAI. Este control protege el uso del proveedor; la aplicación sigue necesitando su configuración de autenticación general para un despliegue con usuarios reales.

La llamada usa `store: false`, imágenes base64 y `text.format` con JSON Schema estricto. Referencias: [imágenes y visión](https://developers.openai.com/api/docs/guides/images-vision) y [salidas estructuradas](https://developers.openai.com/api/docs/guides/structured-outputs).

API: `GET /api/v1/ai/config`, `GET /api/v1/ai/framework/{assessment_id}`, `POST /api/v1/ai/jobs`, `GET /api/v1/ai/jobs`, `GET /api/v1/ai/jobs/{job_id}` y `POST /api/v1/ai/jobs/{job_id}/retry`. Las pruebas usan exclusivamente fixtures y respuestas sintéticas; la integración con un modelo real queda pendiente de configurar una clave verdadera. La cola se ejecuta en un hilo del servidor, con progreso persistido en PostgreSQL o SQLite. Los archivos necesitan almacenamiento persistente: los documentos de la demostración gratuita pueden desaparecer al redeploy.

# DOCIOWEB1

Aplicación web de evaluación criterial basada en la estructura funcional de DOCIO e integrada con el flujo documental de DOCIOWEB.

## Objetivo

DOCIOWEB1 unifica en una aplicación web:

- grupos y alumnado identificado por `student_id`;
- pruebas y evaluaciones;
- cuestiones, saberes, criterios y evidencias;
- corrección criterial y calificación;
- seguimiento e informes;
- importación/exportación `DOCIO_CORRECTION_V1`;
- digitalización de pruebas PDF mediante subida fragmentada, reconstrucción, renderizado de memoria acotada y segmentación por alumno.

## Arquitectura inicial

```text
DOCIOWEB1/
├── backend/              # API FastAPI y dominio DOCIO
│   └── app/
│       ├── api/          # Endpoints HTTP
│       ├── core/         # Configuración
│       ├── domain/       # Modelo de dominio
│       ├── schemas/      # Contratos Pydantic
│       └── services/     # Casos de uso
├── frontend/             # React + TypeScript + Vite
│   └── src/
│       ├── api/          # Cliente API
│       ├── components/   # Componentes reutilizables
│       ├── features/     # Módulos funcionales DOCIO
│       └── pages/        # Vistas principales
├── docs/                 # Arquitectura y contratos
└── render.yaml           # Despliegue web
```

## Módulos funcionales

1. Inicio
2. Grupos
3. Alumnado
4. Pruebas
5. Corrección
6. Criterios y saberes
7. Seguimiento
8. Informes
9. Configuración
10. Digitalización PDF

## Regla de identificación

El alumnado se identifica internamente mediante `student_id`. El nombre no forma parte de la clave de importación o reconciliación.

## Regla curricular

Los criterios de evaluación no se infieren directamente del enunciado. Primero se identifican los saberes básicos efectivamente evaluados y después se asignan exclusivamente los criterios vinculados en la matriz saberes–criterios configurada en DOCIOWEB1.

## Estado

Arquitectura inicial creada. La siguiente fase integra el bloque operativo de DOCIOWEB y desarrolla progresivamente los módulos DOCIO sobre este núcleo.

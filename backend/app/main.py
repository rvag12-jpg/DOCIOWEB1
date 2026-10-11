from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI(
    title="DOCIOWEB1 API",
    version="0.1.0",
    description="API web de evaluación criterial basada en DOCIO.",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health", tags=["system"])
def health() -> dict[str, str]:
    return {"status": "ok", "application": "DOCIOWEB1", "version": "0.1.0"}


@app.get("/api/v1", tags=["system"])
def api_root() -> dict[str, object]:
    return {
        "application": "DOCIOWEB1",
        "version": "0.1.0",
        "modules": [
            "groups",
            "students",
            "assessments",
            "corrections",
            "curriculum",
            "tracking",
            "reports",
            "documents",
        ],
    }

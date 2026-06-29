from dotenv import load_dotenv

load_dotenv()

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from src.presentation.routes.magnetic_resonance import magnetic_resonance_router

app = FastAPI(
    title="Deptha",
    description=(
        "**Deptha** is an AI-assisted MRI analysis pipeline powered by GPT-4o vision.\n\n"
        "Upload a DICOM exam, provide clinical context, and receive a structured radiological "
        "report — complete with per-section findings cards, status badges, and embedded imaging evidence.\n\n"
        "---\n\n"
        "> ⚠️ **Disclaimer:** All output is AI-assisted and intended to support — not replace — "
        "review by a licensed radiologist. Clinical decisions must be made exclusively by the responsible physician."
    ),
    version="0.1.0",
    contact={
        "name": "Deptha",
    },
    license_info={
        "name": "Private — All rights reserved",
    },
    openapi_tags=[
        {
            "name": "Magnetic Resonance",
            "description": "Submit MRI exams for AI-assisted analysis and structured report generation.",
        },
        {
            "name": "Health",
            "description": "Service liveness check.",
        },
    ],
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:5174"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(magnetic_resonance_router)


@app.get(
    "/health",
    tags=["Health"],
    summary="Liveness check",
    description="Returns `200 OK` when the service is up and ready to accept requests.",
)
def health() -> dict:
    return {"status": "ok"}

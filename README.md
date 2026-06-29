# Deptha

AI-assisted MRI analysis pipeline. Upload a DICOM exam, provide clinical context, and get a structured radiological report powered by GPT-4o vision — as a CLI command or a REST API.

## Overview

Deptha processes MRI DICOM files through a four-step pipeline:

1. **Load** — reads all DICOM files from a zip or directory, groups slices by series
2. **Select** — picks evenly-spaced representative slices per series (scouts are skipped)
3. **Encode** — applies window/level normalization and converts slices to base64 PNG
4. **Analyze** — sends images + clinical context to GPT-4o and returns a structured report

The output is a timestamped folder containing a Markdown report and a formatted PDF with per-section findings cards, status badges, and embedded imaging evidence.

### Architecture

```
src/
├── domain/
│   └── models/
│       └── report.py              # Report domain model — saves .md and .pdf
├── infrastructure/                # Connections to the external world
│   ├── dicom_reader.py            # DicomReader
│   ├── image_encoder.py           # ImageEncoder
│   └── openai_client.py           # OpenAIClient
├── application/                   # Business logic
│   ├── entities/
│   │   └── series_summary.py      # SeriesSummary entity
│   ├── prompts/
│   │   └── prompt_knee.md         # Structured knee MRI prompt for GPT-4o
│   └── services/
│       └── analysis_service.py    # AnalysisService — orchestrates the pipeline
└── presentation/                  # Client-facing interfaces
    ├── cli.py                     # CLI
    ├── dependencies.py            # Singleton dependency wiring
    └── routes/
        └── magnetic_resonance.py  # FastAPI router
```

Dependencies flow inward only: `presentation → application → infrastructure`.

---

## Requirements

- Python 3.11+
- An OpenAI API key with access to `gpt-4o`

## Setup

**1. Navigate to the project:**

```bash
cd Deptha
```

**2. Create and activate a virtual environment:**

```bash
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
```

**3. Install dependencies:**

```bash
pip install pydicom Pillow openai python-dotenv numpy fpdf2 "fastapi>=0.111" "uvicorn[standard]>=0.29"
```

**4. Configure environment variables:**

```bash
cp .env.example .env
```

```env
OPENAI_API_KEY=sk-...
OPENAI_MODEL=gpt-4o   # optional, defaults to gpt-4o
```

> Keep `.env` outside version control — it is listed in `.gitignore`.

---

## Usage

### CLI

```bash
python -m src.presentation.cli \
  --input  data/input/exam.zip \
  --context "Post-op ACL reconstruction + lateral meniscal suture, 3 months. \
             Intermittent joint locking and pain on full extension. Mild effusion on clinical exam." \
  --slices 8
```

| Flag | Required | Default | Description |
|---|---|---|---|
| `--input` | yes | — | Path to DICOM `.zip` or directory |
| `--context` | yes | — | Free-text clinical context for the patient |
| `--slices` | no | `5` | Number of slices to sample per series |

---

### API

Start the server:

```bash
uv run uvicorn src.main:app --reload --host 0.0.0.0 --port 8000
```

Interactive API docs are available automatically at:

- **Swagger UI** → [http://localhost:8000/docs](http://localhost:8000/docs)
- **ReDoc** → [http://localhost:8000/redoc](http://localhost:8000/redoc)

#### Submit an exam for analysis

```bash
curl -X POST http://localhost:8000/magnetic-resonance/analyse-exam \
  -H "Content-Type: application/json" \
  -d '{
    "input_path": "data/input/exam.zip",
    "patient_context": "Post-op ACL reconstruction + lateral meniscal suture, 3 months. Intermittent joint locking and pain on full extension. Mild effusion on clinical exam.",
    "slices_per_series": 8
  }'
```

**Response — 202 Accepted:**

```json
{
  "message": "Analysis queued. The report will be written to the output directory once processing completes.",
  "output_dir": "data/output/2026-06-29_14-30-00"
}
```

The endpoint returns immediately. The full pipeline runs in the background — once complete, the report is written to `output_dir`.

#### Health check

```bash
curl http://localhost:8000/health
# {"status":"ok"}
```

---

## Output

Each run creates a timestamped folder under `data/output/`:

```
data/output/
└── 2026-06-29_14-30-00/
    ├── report.md    ← full Markdown report
    └── report.pdf   ← formatted PDF with findings cards and imaging evidence
```

Both files include:

- Metadata for each series (modality, total slices, slices analysed)
- Structured radiological findings with status classification
- Per-section embedded DICOM images (PDF only)
- Clinical correlation and a direct answer to the clinical question

---

## Disclaimer

Deptha is a research and development tool. Its output is **not a substitute for a qualified radiologist's report** and must not be used for clinical decision-making without professional review.

# Deptha

AI-assisted MRI analysis pipeline. Upload a DICOM exam, provide clinical context, and get a structured radiological report powered by GPT-4o vision.

## Overview

Deptha processes MRI DICOM files through a four-step pipeline:

1. **Load** — reads all DICOM files from a zip or directory, groups slices by series
2. **Select** — picks evenly-spaced representative slices per series (scouts are skipped)
3. **Encode** — applies window/level normalization and converts slices to base64 PNG
4. **Analyze** — sends images + clinical context to GPT-4o and returns a structured report

### Architecture

```
src/
├── domain/
│   └── models/
│       └── report.py         # Report domain model (saves .md and .pdf)
├── infrastructure/           # external world (DICOM I/O, image encoding, OpenAI API)
│   ├── dicom_reader.py       # DicomReader
│   ├── image_encoder.py      # ImageEncoder
│   └── openai_client.py      # OpenAIClient
├── application/              # business logic
│   ├── entities/
│   │   └── series_summary.py # SeriesSummary entity
│   └── services/
│       └── analysis_service.py  # AnalysisService
└── presentation/             # user-facing interface
    ├── cli.py                # CLI
    └── dependencies.py       # singleton wiring
```

Dependencies flow inward only: `presentation → application → infrastructure`.

---

## Requirements

- Python 3.11+
- An OpenAI API key with access to `gpt-4o`

## Setup

**1. Clone and navigate to the project:**

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
pip install pydicom Pillow openai python-dotenv numpy fpdf2
```

**4. Configure environment variables:**

Copy `.env.example` to `.env` and fill in your key:

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

```bash
python -m src.main \
  --input  data/input/exam.zip \
  --context "Post-op ACL reconstruction + lateral meniscal suture, 3 months. Pain and joint locking."
```

### Options

| Flag | Required | Default | Description |
|---|---|---|---|
| `--input` | yes | — | Path to DICOM `.zip` or directory |
| `--context` | yes | — | Free-text clinical context for the patient |
| `--slices` | no | `5` | Number of slices to sample per series |

### Prompts

The analysis prompt is resolved automatically by the service from `src/application/prompts/prompt_knee.md`. No CLI flag needed. To add a new prompt for a different body part, place a `.md` file in that directory — it must contain `{patient_context}` as a placeholder.

---

## Output

Each run creates a timestamped folder under `data/output/` containing two files:

```
data/output/
└── 2026-06-29_12-01-05/
    ├── report.md    ← full markdown report
    └── report.pdf   ← formatted PDF for sharing with non-technical users
```

Both files include:

- Metadata for each series (modality, total slices, slices analysed)
- Structured radiological findings
- Clinical correlation and contextual observations

The analysis is also printed to stdout at the end of the run.

---

## Disclaimer

Deptha is a research and development tool. Its output is **not a substitute for a qualified radiologist's report** and must not be used for clinical decision-making without professional review.

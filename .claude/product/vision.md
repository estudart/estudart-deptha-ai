# Product Vision — Deptha

## What This System Does

Radiologists are scarce, expensive, and overloaded. Patients with musculoskeletal MRI exams
often wait days or weeks for a report. Deptha is an AI-assisted analysis pipeline that takes
a DICOM exam as input, applies clinical context provided by the user, and returns a structured
radiological report in minutes — powered by GPT-4o vision.

The initial focus is knee MRI, with post-operative cases (ACL reconstruction, meniscal repair)
as the primary use case validated in the MVP.

## Primary Users

- **Patients** — upload their own exam and receive a structured preliminary report
- **Clinicians** — use Deptha as a second opinion or pre-read tool before formal radiologist review
- **Researchers** — use the pipeline to process large DICOM datasets

## Core Workflow

1. User provides a DICOM exam (zip or directory) and a free-text clinical context
2. Deptha loads all series, filters scouts and localizers, samples representative slices
3. Slices are normalized and converted to PNG images
4. Images + clinical context are sent to GPT-4o vision with a structured radiological prompt
5. The report is saved as Markdown and printed to stdout

## Non-Goals

- Replacing a licensed radiologist — Deptha is a decision-support tool, not a diagnostic device
- Real-time or streaming analysis
- Building a web UI in this phase (CLI only for MVP)
- Storing patient data persistently — exams are processed in memory and deleted after the run

## Why This Matters

Musculoskeletal MRI is one of the highest-volume imaging modalities globally. Post-operative
follow-up exams are particularly repetitive — the same structures, the same findings, the same
report format. This is a high-value automation target.

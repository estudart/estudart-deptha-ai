# MRI Analysis Pipeline

## Overview

```
Input (zip / dir)
       │
       ▼
 DicomReader.load_series()
       │  groups files by SeriesDescription, sorted by InstanceNumber
       ▼
 DicomReader.is_relevant() + select_slices()
       │  drops scouts/localizers, samples n evenly-spaced slices per series
       ▼
 ImageEncoder.encode_series()
       │  normalizes pixel values (window/level), converts to base64 PNG
       ▼
 OpenAIClient.call_vision()
       │  builds message content, calls gpt-4o, returns report text
       ▼
 Report (dataclass)
       │  saved as Markdown to output path
       ▼
 stdout
```

---

## Class Responsibilities

### `DicomReader` (`infrastructure/dicom_reader.py`)

| Method | Input | Output | Notes |
|---|---|---|---|
| `extract_zip` | zip path, target dir | extracted dir path | |
| `load_series` | dicom dir | `dict[label, list[Dataset]]` | sorted by InstanceNumber |
| `series_metadata` | series dict | `list[dict]` | label, slices, modality, rows, cols |
| `is_relevant` | series label | bool | drops SKIP_KEYWORDS |
| `select_slices` | slice list, n | slice list | evenly-spaced, always includes first/last |

`SKIP_KEYWORDS = ["localizer", "scout", "loc", "3-plane", "survey"]`

### `ImageEncoder` (`infrastructure/image_encoder.py`)

| Method | Input | Output | Notes |
|---|---|---|---|
| `encode_series` | selected series dict | `dict[label, list[str]]` | base64 PNG per slice |
| `_to_base64_png` | Dataset | str | private |
| `_normalize` | Dataset | np.ndarray uint8 | applies RescaleSlope/Intercept + window/level |

Window/level fallback: if no WindowCenter/WindowWidth in header, uses `arr.min()` / `arr.max()`.

### `OpenAIClient` (`infrastructure/openai_client.py`)

| Method | Input | Output | Notes |
|---|---|---|---|
| `call_vision` | images dict, context, prompt_path | str | main entry point |
| `_build_content` | prompt, context, images | list[dict] | series label as text separator between image blocks |
| `_load_prompt` | prompt_path | str | reads file or falls back to `_default_prompt()` |
| `_default_prompt` | — | str | built-in generic MSK prompt |

Model is read from `OPENAI_MODEL` env var, defaults to `gpt-4o`.

### `AnalysisService` (`application/analysis_service.py`)

| Method | Input | Output | Notes |
|---|---|---|---|
| `run` | input_path, context, prompt_path, slices_per_series | Report | main orchestration |
| `_resolve_input` | input_path | dicom_dir path | extracts zip if needed |

Temp dirs created for zip extraction are always deleted in `finally`.

---

## Data Contracts

### Series dict
```python
dict[str, list[pydicom.Dataset]]
# key: SeriesDescription (falls back to SeriesInstanceUID)
# value: slices sorted by InstanceNumber
```

### Images dict
```python
dict[str, list[str]]
# key: series label (same as series dict)
# value: base64-encoded PNG strings
```

### Report
```python
@dataclass
class Report:
    patient_context: str
    series_summaries: list[SeriesSummary]
    analysis: str              # raw text from GPT-4o
    generated_at: datetime
```

---

## Prompt Contract

Prompt files must contain `{patient_context}` as the only placeholder.
It is filled via `str.format(patient_context=...)` before sending to the API.
A knee-specific prompt template is at `docs/prompt_knee.txt`.

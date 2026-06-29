# Feature: MRI Analysis

## What It Does

Takes a DICOM exam (zip or directory) + clinical context string, runs the full pipeline,
and returns a structured radiological report as a Markdown file.

## Entry Point

```bash
python main.py \
  --input  data/input/exam.zip \
  --context "Post-op ACL + lateral meniscal suture, 3 months. Pain and joint locking." \
  --prompt  docs/prompt_knee.txt \
  --slices  7 \
  --output  data/output/report.md
```

## CLI Arguments

| Flag | Required | Default | Description |
|---|---|---|---|
| `--input` | yes | — | DICOM `.zip` or directory |
| `--context` | yes | — | Free-text clinical context |
| `--prompt` | no | built-in | Custom prompt `.txt` with `{patient_context}` placeholder |
| `--slices` | no | `5` | Slices sampled per series |
| `--output` | no | `data/output/report.md` | Output path |

## Pipeline Steps

1. **Resolve input** — if zip, extract to temp dir; always clean up in `finally`
2. **Load series** — `DicomReader.load_series()` walks the directory, groups by `SeriesDescription`
3. **Filter + select** — drop series matching `SKIP_KEYWORDS`; sample `n` evenly-spaced slices
4. **Encode** — `ImageEncoder.encode_series()` normalizes pixel data, returns base64 PNGs
5. **Analyze** — `OpenAIClient.call_vision()` sends images + context to GPT-4o
6. **Report** — `Report.save()` writes Markdown; `CLI` prints to stdout

## Prompt Template

The prompt must contain `{patient_context}` as the only placeholder. Two options:

- **Built-in** (`OpenAIClient._default_prompt`): generic MSK prompt, covers findings, impression, recommendations
- **Knee-specific** (`src/application/prompts/prompt_knee.md`): structured by anatomical region (ligaments, menisci, cartilage, periarticular, fluid)

Pass the knee prompt with `--prompt src/application/prompts/prompt_knee.md` for post-op knee cases.

## Output Format

```markdown
# Deptha — Laudo de RM
Gerado em: YYYY-MM-DD HH:MM:SS

## Contexto clínico
<patient_context>

## Séries analisadas
- <SeriesLabel>: <total> cortes totais, <analysed> analisados (<modality>)
...

## Análise
<GPT-4o report text>
```

## Known Limitations

- Window/level fallback (no DICOM header values) uses raw pixel range — may produce suboptimal contrast
- Series with identical `SeriesDescription` are merged into one group
- GPT-4o context window limits total image payload — keep `--slices` ≤ 7 per series for large exams

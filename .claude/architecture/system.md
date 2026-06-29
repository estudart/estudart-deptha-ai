# System Architecture

## Style: Clean Architecture

Dependencies flow inward only — never outward, never sideways:

```
Presentation  →  Application  →  Infrastructure
```

### Presentation (`src/presentation/`)

CLI boundary only. `CLI` parses arguments, calls a getter from `dependencies.py`,
and delegates to the service. No business logic, no DICOM operations, no OpenAI calls.

```python
# Good
class CLI:
    def run(self) -> None:
        args = self._parse_args()
        service = get_analysis_service()
        report = service.run(input_path=args.input, ...)
        report.save(args.output)

# Bad — business logic inside CLI
class CLI:
    def run(self) -> None:
        reader = DicomReader()          # wrong layer
        series = reader.load_series()  # wrong layer
```

### Application (`src/application/`)

All business logic. `AnalysisService` orchestrates the pipeline: it coordinates
`DicomReader`, `ImageEncoder`, and `OpenAIClient`, and returns a `Report` domain object.
Domain models (`Report`, `SeriesSummary`) also live here — they are pure dataclasses with no I/O.

**Rule:** `AnalysisService` never imports from `openai` directly. It calls `OpenAIClient`
methods only. The service knows *what* to do; the client knows *how* to call the API.

### Infrastructure (`src/infrastructure/`)

External world only. Three classes, each owning one external concern:

| Class | Owns |
|---|---|
| `DicomReader` | DICOM file I/O, zip extraction, slice ordering, series filtering |
| `ImageEncoder` | Pixel normalization, window/level, base64 PNG conversion |
| `OpenAIClient` | OpenAI SDK calls, prompt loading, message construction |

No business logic in infrastructure. These classes are stateless — they receive inputs,
call external systems, and return outputs.

---

## Dependency Injection

All wiring happens in `src/presentation/dependencies.py`. This is the only place
where instances are created. `CLI` never instantiates anything directly — it always
calls a getter.

### Getter Pattern

Every singleton follows the same lazy-init pattern:

```python
_analysis_service: AnalysisService | None = None

def get_analysis_service() -> AnalysisService:
    global _analysis_service
    if _analysis_service is None:
        _analysis_service = AnalysisService(
            dicom_reader=DicomReader(),
            image_encoder=ImageEncoder(),
            openai_client=get_openai_client(),
        )
    return _analysis_service
```

### Shared Infrastructure Singletons

`get_openai_client()` is the shared singleton. Never construct `OpenAIClient` inside
a service — always pass via constructor injection.

---

## Adding a New Feature: Checklist

1. Add infrastructure class or method if a new external system is needed
2. Add or extend a service in `application/`
3. Add a getter in `dependencies.py`
4. Wire the CLI flag in `presentation/cli.py`
5. Write `.claude/features/{feature}.md`

---

## Never Do

- Import anything from `presentation` into `application` or `infrastructure`
- Import from `openai` SDK inside `AnalysisService`
- Instantiate `DicomReader`, `ImageEncoder`, or `OpenAIClient` outside `dependencies.py`
- Put business logic (slice selection, series filtering) inside infrastructure classes
- Put I/O (file reads, API calls) inside `AnalysisService`
- Add global state to infrastructure classes

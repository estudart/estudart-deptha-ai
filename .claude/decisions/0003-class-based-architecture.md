# ADR 0003 — Class-Based Architecture Over Module-Level Functions

## Status

Accepted

## Context

The initial implementation used module-level functions (e.g. `def load_series(...)`,
`def call_vision(...)`). This was flagged as insufficient for a production-grade codebase.

## Decision

All logic lives inside **classes**. No public module-level functions except getters in `dependencies.py`.

| Layer | Class |
|---|---|
| Infrastructure | `DicomReader`, `ImageEncoder`, `OpenAIClient` |
| Application | `AnalysisService` |
| Presentation | `CLI` |
| DI wiring | `get_openai_client()`, `get_analysis_service()` in `dependencies.py` |

## Reasons

- Classes make dependencies explicit via constructor injection — testable without monkeypatching
- Encapsulation: private methods (`_normalize`, `_build_content`) are not importable accidentally
- Consistent with the reference architecture (`ValuePathAI` repo) used as the project standard
- Easier to extend: adding a second LLM provider means adding a new class, not touching existing functions

## Consequences

- Slightly more boilerplate than loose functions for a CLI tool
- All infrastructure classes must be stateless (no mutable instance vars after `__init__`)
- `dependencies.py` is the mandatory wiring point — adding a new dependency always requires a getter there

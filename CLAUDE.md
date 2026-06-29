# Deptha — Claude Instructions

## Read These First

Before touching any file, read:

- `.claude/product/vision.md` — what this system does and why
- `.claude/architecture/system.md` — clean architecture layers, rules, dependency flow
- `.claude/architecture/pipeline.md` — MRI pipeline steps, class responsibilities, data contracts
- `.claude/standards/backend.md` — coding standards, naming conventions, what not to do

## Features

- `.claude/features/mri-analysis.md` — end-to-end MRI analysis (DICOM → report)

## Key Decisions (read before changing anything architectural)

- `.claude/decisions/0001-openai-gpt4o-vision.md` — why GPT-4o, not a local model
- `.claude/decisions/0002-dicom-zip-input.md` — why zip as the primary input format
- `.claude/decisions/0003-class-based-architecture.md` — why classes over functions

## Docs Are Not Optional — Keep Them Alive

Every time you change code, ask: does any `.claude/` doc need updating?

| You changed | Check these docs |
|---|---|
| A class method (added, renamed, removed) | `architecture/system.md`, `architecture/pipeline.md` |
| A CLI flag or argument | `features/mri-analysis.md` |
| Infrastructure class behaviour | `architecture/pipeline.md` |
| `dependencies.py` (new getter, new singleton) | `architecture/system.md` |
| Prompt logic or template | `features/mri-analysis.md` |
| A decision that was already made differently | `decisions/` — add a new ADR, do not silently override |

**The rule**: if you touch code, you touch the relevant doc in the same response. Stale docs are worse than no docs.

---

## Hard Rules (no exceptions)

- Dependencies flow inward only: `presentation → application → infrastructure`
- All singletons in `dependencies.py` — nowhere else
- `DicomReader`, `ImageEncoder`, `OpenAIClient` are stateless — no global state inside them
- `OpenAIClient` is the only class allowed to call the OpenAI SDK
- `AnalysisService` is the only class allowed to orchestrate the pipeline
- `CLI` is the only class allowed to parse arguments or print to stdout
- Never instantiate infrastructure classes outside `dependencies.py`
- Never import from `presentation` inside `application` or `infrastructure`

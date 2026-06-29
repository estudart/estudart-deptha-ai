# Backend Standards

## Language & Runtime

- Python 3.11+
- No `print()` inside services or infrastructure — use `logging.getLogger("deptha")`
- `print()` is only allowed in `CLI` for final report output to stdout

## Architecture

- Constructor injection only — classes receive dependencies via `__init__`, never instantiate them internally
- All singletons created and cached in `dependencies.py` — nowhere else
- Infrastructure classes are stateless — no instance variables that change after `__init__`

## Classes

- One class per file, file named after the class in snake_case
- Private methods prefixed with `_`
- No `@staticmethod` unless the method genuinely has no access to instance or class state
- `@dataclass` for domain models — no business logic, no I/O inside dataclasses

## Naming

- Classes: `PascalCase`
- Methods and variables: `snake_case`
- Constants: `UPPER_SNAKE_CASE` at class or module level
- Getters in `dependencies.py`: `get_{thing}()` — e.g. `get_openai_client()`, `get_analysis_service()`

## Type Hints

- All public method signatures must be fully typed (parameters and return type)
- Use `X | None` not `Optional[X]`
- Use `list[X]` / `dict[K, V]` not `List[X]` / `Dict[K, V]` (Python 3.10+ generics)

## Error Handling

- Raise on unrecoverable errors — do not silently swallow exceptions in the pipeline
- Log a warning and skip unreadable DICOM files — do not abort the whole series
- Temp dirs must always be cleaned up in `finally` blocks

## Comments

- No comments explaining what the code does — use clear method names instead
- Only comment when the WHY is non-obvious: a hidden constraint, a pydicom quirk, an API limitation

## What Not to Do

- Do not use `global` outside `dependencies.py`
- Do not call `OpenAI()` outside `dependencies.py`
- Do not use `argparse` outside `CLI._parse_args()`
- Do not hardcode model names — always read from `OPENAI_MODEL` env var
- Do not pass raw `pydicom.Dataset` objects across layer boundaries — convert to base64 in infrastructure before handing to application

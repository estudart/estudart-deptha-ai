# ADR 0001 — Use OpenAI GPT-4o for Vision Analysis

## Status

Accepted

## Context

MRI analysis requires a model capable of interpreting grayscale medical images with
clinical-grade attention to detail. Options considered:

1. **GPT-4o (OpenAI)** — frontier vision model, strong medical imaging performance, API-based
2. **Claude 3.5 Sonnet (Anthropic)** — comparable vision capability, similar API model
3. **Local model (LLaVA, MedSAM, etc.)** — open-source, no data leaves the machine
4. **Google Gemini 1.5 Pro** — strong long-context, good vision

## Decision

Use **GPT-4o** via the OpenAI API.

## Reasons

- Founder already has OpenAI API credits — zero marginal cost to start
- GPT-4o has demonstrated strong performance on medical imaging benchmarks
- API-based approach means no GPU infrastructure required for MVP
- Easy to swap to another provider later — `OpenAIClient` is the only class that touches the SDK

## Consequences

- Patient image data is sent to OpenAI's servers — users must be informed and consent
- Latency depends on OpenAI API availability
- Model is configurable via `OPENAI_MODEL` env var — switching to a different model requires no code change

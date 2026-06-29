# ADR 0002 — Accept DICOM Exam as Zip or Directory

## Status

Accepted

## Context

DICOM exams are distributed in multiple formats depending on the source:
- Hospital PACS exports: zip archive containing a flat or nested folder of `.dcm` files
- CD/DVD exports: directory tree with optional DICOMDIR
- Research datasets: flat directories of `.dcm` files

The pipeline needs to handle both zip and directory inputs without user friction.

## Decision

Accept **both zip archives and directories** as `--input`. The `DicomReader` handles
zip extraction transparently: if the input suffix is `.zip`, it extracts to a temp dir,
processes, and deletes the temp dir in `finally`.

## Reasons

- Zip is the most common format patients receive from hospitals
- Directory support covers local workflows and research use cases
- Single `--input` flag keeps the CLI simple — no need for `--zip` vs `--dir`
- Temp dir cleanup in `finally` ensures no residual data on disk

## Consequences

- Zip files are fully extracted to disk before processing — large exams require sufficient disk space
- The temp dir path is opaque to the user (under `/tmp/deptha_*`)
- DICOMDIR files are not parsed — series are discovered by walking all files recursively

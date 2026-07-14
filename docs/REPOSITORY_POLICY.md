# Repository Policy

- `main` represents the latest stable, reproducible candidate, not work in progress.
- Each active algorithm direction uses its own short-lived development branch.
- Completed stages are preserved with annotated tags instead of long-lived branches.
- Generated solver solutions are not committed to the ordinary Git tree.
- The standard evidence package is JSONL, CSV summaries, and JSON/Markdown reports.
- Historical configurations remain addressable for evidence replay but are hidden from normal CLI help unless `--include-historical-configs` is supplied.

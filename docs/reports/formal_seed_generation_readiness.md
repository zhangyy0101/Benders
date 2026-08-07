# Formal-seed generation readiness

> Historical report. This readiness decision applies only to the superseded
> `rolling-v4.4` / algorithm `v1.4.7` design and seeds `1000--1009`, whose
> outcomes were subsequently opened. It does not authorize or describe the
> current TRE confirmatory experiment. See
> `tre_v173_formal_instance_generation_readiness.md` instead.

## Decision

The algorithm and data interfaces are ready to be frozen before formal seed
generation. Formal seeds 1000--1009 have not been instantiated by this
readiness work.

The five-method interface gate contains 120 valid preflight rows from 24
immutable seed-700--702 instances. All five methods completed every instance,
placed every realized export box, passed independent state validation, and
remained within the common online-decision limit.

## Frozen boundary

- Problem protocol: `rolling-v4.4-physical-capacity-recovery`
- Candidate: `lead-aware-aggregate-lp-screened-repair-v1.4.7`
- Candidate configuration: `full_bottleneck`
- Internal comparator: `core_start`
- External baselines: `kp_dos`, `kp_sg`, `dra_rpm`
- External-baseline protocol:
  `adapted-literature-baselines-v1.1-sparse-cached`
- Preprocessing: `lead-aware-aggregate-lp-sparse-indexed-v5`
- Result schema: `rolling-results-v11`
- Runtime: strict end-to-end online-decision wall time
- Solver threads: one per method
- Common physical-capacity recovery: enabled for every method
- Model box domain: 20/40 feet and STD/HIGH
- Yard scope: Yangshan areas whose function includes OF

The data-family allocation, eight-profile semi-synthetic specification,
formal seeds, method partitions, time budgets, output roots, result counts,
metrics, and reporting separation are machine-readable in:

- `docs/specs/pnc_yangshan_v2_formal_instance_spec.json`;
- `docs/specs/formal_run_manifest_v2.json`.

## Authorized generation entry point

The PNC--Yangshan formal bundles must be created only with:

```powershell
python scripts/prepare_pnc_yangshan_v2_formal_instances.py `
  --output-root local_results/protocol_v2_pnc_yangshan/formal_instances_v2
```

Before generating anything, the entry point rejects a dirty Git tree, a
changed seed/profile/domain specification, an incomplete five-method audit,
missing source artifacts, a changed method set, or an existing output root.
It then verifies every bundle's fixed PNC call IDs, source hashes, supported
attribute domain, OF-yard inputs, volume reconciliation, and independent
zero-shortage integer certificate.

It writes three immutable indexes:

- all 80 bundles;
- 10 central bundles for the five-method main comparison;
- 70 robustness bundles for candidate versus `core_start`.

Overwrite and partial-resume behavior are intentionally absent. A failed
generation attempt must be retained for diagnosis or moved to a separately
labelled failed-attempt directory; it may not be silently combined with a
fresh formal index.

## Pre-generation checks

The final gate consists of:

1. complete repository test suite passing;
2. no Python syntax or import failure in formal entry points;
3. clean Git commit containing the frozen code, specifications, and tests;
4. `--check-only` returning `PASS` from that same commit;
5. formal output root absent.

The `--check-only` command is:

```powershell
python scripts/prepare_pnc_yangshan_v2_formal_instances.py --check-only
```

It validates prerequisites without building a case or initializing any
formal-seed realization. The next action after this report is therefore the
single authorized generation command, not further algorithm tuning.

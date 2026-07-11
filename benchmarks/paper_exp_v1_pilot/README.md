# paper-exp-v1-pilot1

All nine files are deterministic **synthetic** pilot benchmarks for development, validation, and difficulty calibration. They are not real-port data and must not be used as final paper results.

Seeds are permanent: S01–S03 = 1101–1103, M01–M03 = 2101–2103, L01–L03 = 3101–3103. Instances use generator `synthetic-yard-v1`, schema `yard-bay-instance-v1`, and problem protocol `paper-exp-v1`.

Regenerate with `python scripts/build_pilot_benchmarks.py`. Existing equal digests are retained; a conflicting file fails unless explicit `--overwrite` is supplied. Verify with `python scripts/audit_benchmarks.py benchmarks/paper_exp_v1_pilot`. No solver performance was used to select or tune these instances.

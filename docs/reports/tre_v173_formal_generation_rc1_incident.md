# TRE v1.7.3 formal generation RC1 incident

## Outcome

The RC1 formal-instance generation process started on 2026-08-08 at 01:46:03
Asia/Shanghai and terminated during PNC--Yangshan bundle construction. It was
an operating-path failure, not an optimization infeasibility, model error or
algorithm result.

The failing temporary filename resolved to 264 characters on the Windows
host. Its parent directory existed and the disk had approximately 232 GB free.
Python therefore failed at the classic Windows path boundary while opening the
temporary bundle file.

## Preserved evidence

- Commit: `178802f2d22ebc40f37312cb6fb056f66ea096f9`.
- Tag: `rolling-v4.6-objective-only-stability-formal-input-rc1`.
- Partial bundles: 70.
- Assembly audits: 70.
- Files: 140.
- Total bytes: 45,278,224.
- Formal indexes: 0.
- Formal result rows: 0.
- Quarantine: `local_results/quarantine_rc1_path_failure_20260808`.
- Standard-output SHA-256:
  `fbd87b7c356aeea5fd5db29dbf92585f3aa778c9e87494beb8fa29d8fd830ece`.
- Standard-error SHA-256:
  `3f02a53a898a32f8b6c5e880aa520062960a3490bb9abc2c9dda8bddee1ba379`.

The quarantined files must not be resumed, indexed, merged with RC2 or used as
formal evidence.

## Corrective action

RC2 shortens both formal instance and result roots to
`local_results/tre_v3_rc2`, validates the longest known temporary filename
before generation, and rejects a non-frozen output root. The entire 280-bundle
matrix will be regenerated from zero.

This correction changes no model, algorithm, source data, seed, weight,
parameter profile, method matrix, time budget or statistical rule. The same
preregistered seeds `2000--2009` are retained because no algorithm outcome was
produced or inspected and no experimental choice was changed from partial
instance construction.

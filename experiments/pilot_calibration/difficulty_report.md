# Pilot difficulty calibration

This is a development pilot, not a final paper result. The first screen uses S01/M01/L01 only, with 15/30/45 second budgets. S01 stochastic configurations use seeds 0/1/2; Medium and Large currently use seed 0 only.

- **Small**: feasible rate 100.0%, optimal-status rate 89.5%, median gap 0.019615708431303624, median runtime 3.96s.
- **Medium**: feasible rate 100.0%, optimal-status rate 54.5%, median gap 0.029983225355215033, median runtime 21.68s.
- **Large**: feasible rate 81.8%, optimal-status rate 0.0%, median gap 0.9777648397870284, median runtime 45.77s.

KPI signals with zero observed range: none.

## Preliminary judgment

- Small retains the exact-crosscheck role: the separate 600-second gate proved S01–S03 exact, while this short screen is mostly optimal.
- Medium finds feasible solutions consistently and shows mixed optimality/gaps, so it can discriminate configurations in the next round.
- Large is materially harder: no run reports optimal and some configurations find no incumbent, while most still return feasible solutions. It is usable for finite-time comparison but needs more instances/seeds before freezing its scale.
- Pilot1 is retained without modification; no evidence yet requires `paper_exp_v1_pilot2`.

Final algorithm is not frozen in Task 10.

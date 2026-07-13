from scripts.run_fast_internal_screen import improvement_flags, meaningful


def test_meaningful_requires_configured_relative_improvement():
    assert meaningful(111.0, 100.0, 1)
    assert not meaningful(100.5, 100.0, 1)
    assert meaningful(89.0, 100.0, -1)


def test_missing_incumbent_is_first_feasible_evidence():
    def row(feasible, **optimization):
        return {"status": {"feasible_incumbent_found": feasible}, "optimization": optimization, "timing": {}}

    flags = improvement_flags(row(True), row(False))
    assert flags["feasible"] is True
    assert not any(value for key, value in flags.items() if key != "feasible")

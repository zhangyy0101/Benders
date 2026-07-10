import inspect
import main
def test_summary_separates_core_and_refined_solution():
    source=inspect.getsource(main.main); assert "core_best_solution.json" in source and "attribute_refined_solution.json" in source
def test_summary_contains_no_benders_claim():
    assert "benders" not in inspect.getsource(main).lower()


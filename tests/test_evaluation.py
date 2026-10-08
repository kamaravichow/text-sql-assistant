from sqlagent.evaluation import CaseResult, normalize_value, results_match, summarize_results


def test_numeric_and_date_normalisation():
    assert normalize_value(2022) == normalize_value(2022.0) == normalize_value("2022.00")
    assert normalize_value("2024-01-01T00:00:00") == normalize_value("2024-01-01")
    assert normalize_value(0.0437) == normalize_value(0.04373)
    assert normalize_value(0.0437) != normalize_value(0.0551)
    assert normalize_value(None) != normalize_value("")


def test_results_match_ignores_row_and_column_order_and_aliases():
    gold = [["US", 3], ["DE", 5]]
    assert results_match(gold, [[5, "DE"], [3, "US"]])
    assert not results_match(gold, [["US", 3]])
    assert not results_match(gold, [["US", 3], ["DE", 6]])


def test_duplicates_matter():
    assert not results_match([[1], [1]], [[1]])


def test_summary_metrics():
    def r(i, ok, attempts, diff):
        return CaseResult(str(i), "q", diff, "completed" if ok else "failed", ok, attempts, 1.0 + i)

    s = summarize_results([r(0, True, 0, "easy"), r(1, True, 2, "hard"), r(2, False, 3, "hard")])
    assert s["execution_accuracy"] == 0.667
    assert s["by_difficulty"]["hard"]["execution_accuracy"] == 0.5
    assert s["needed_self_correction"] == 2 and s["recovered_by_self_correction"] == 1

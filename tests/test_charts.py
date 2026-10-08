import pandas as pd

from sqlagent.charts import ChartSpec, build_figure, heuristic_spec, parse_spec, to_dataframe


def test_dates_are_detected_and_line_chart_chosen():
    df = to_dataframe(["month", "revenue"], [["2024-01-01", 10.0], ["2024-02-01", 12.5]])
    assert pd.api.types.is_datetime64_any_dtype(df["month"])
    assert heuristic_spec(df).chart_type == "line"


def test_category_and_number_gives_bar():
    df = to_dataframe(["country", "n"], [["US", 3], ["DE", 5]])
    spec = heuristic_spec(df)
    assert (spec.chart_type, spec.x, spec.y) == ("bar", "country", "n")


def test_single_value_has_no_chart():
    assert heuristic_spec(to_dataframe(["n"], [[42]])).chart_type == "none"
    assert heuristic_spec(to_dataframe(["n"], [])).chart_type == "none"


def test_parse_spec_accepts_valid_and_rejects_unknown_columns():
    df = to_dataframe(["country", "n"], [["US", 3], ["DE", 5]])
    ok = parse_spec('Sure: {"chart_type": "bar", "x": "country", "y": "n", "title": "T"}', df)
    assert ok and ok.title == "T"
    assert parse_spec('{"chart_type": "bar", "x": "nope", "y": "n"}', df) is None
    assert parse_spec('{"chart_type": "donut"}', df) is None
    assert parse_spec("no json here", df) is None


def test_pie_with_too_many_slices_is_rejected():
    df = to_dataframe(["k", "v"], [[f"c{i}", i] for i in range(10)])
    assert parse_spec('{"chart_type": "pie", "x": "k", "y": "v"}', df) is None


def test_build_figure_returns_plotly_json():
    df = to_dataframe(["country", "n"], [["US", 3], ["DE", 5]])
    fig = build_figure(ChartSpec(chart_type="bar", x="country", y="n", title="By country"), df)
    assert fig["data"][0]["type"] == "bar"
    assert build_figure(ChartSpec(chart_type="none"), df) is None

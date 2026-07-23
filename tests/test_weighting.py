"""Regression checks for respondent-level weighting."""

from __future__ import annotations

import unittest

import pandas as pd

from src.tables import build_weighted_respondent_export_dataframe, generate_workbook_package
from src.weighting import FINAL_WEIGHT_COLUMN


def _weighted_dataframe() -> pd.DataFrame:
    """Return a small intentionally imbalanced comparison dataset."""
    rows = []
    rows.extend({"cell": "Control", "gender": "M", "Outcome": "Yes"} for _ in range(9))
    rows.append({"cell": "Control", "gender": "F", "Outcome": "No"})
    rows.append({"cell": "Test", "gender": "M", "Outcome": "Yes"})
    rows.extend({"cell": "Test", "gender": "F", "Outcome": "No"} for _ in range(9))
    return pd.DataFrame(rows)


def _unequal_weighted_dataframe() -> pd.DataFrame:
    """Return imbalanced comparison groups where equal-group averaging matters."""
    rows = []
    rows.extend({"cell": "Control", "gender": "M", "Outcome": "Yes"} for _ in range(90))
    rows.extend({"cell": "Control", "gender": "F", "Outcome": "No"} for _ in range(10))
    rows.append({"cell": "Test", "gender": "M", "Outcome": "Yes"})
    rows.extend({"cell": "Test", "gender": "F", "Outcome": "No"} for _ in range(9))
    return pd.DataFrame(rows)


def _micro_community_dataframe() -> pd.DataFrame:
    """Return a micro-community dataset where only TL should receive weights."""
    rows = []
    rows.extend({"cell": "0", "micro_community": "TL", "gender": "M", "Outcome": "Yes"} for _ in range(9))
    rows.append({"cell": "0", "micro_community": "TL", "gender": "F", "Outcome": "No"})
    rows.append({"cell": "1", "micro_community": "TL", "gender": "M", "Outcome": "Yes"})
    rows.extend({"cell": "1", "micro_community": "TL", "gender": "F", "Outcome": "No"} for _ in range(9))
    rows.extend({"cell": "0", "micro_community": "AO", "gender": "M", "Outcome": "Yes"} for _ in range(4))
    rows.extend({"cell": "1", "micro_community": "AO", "gender": "F", "Outcome": "No"} for _ in range(4))
    rows.extend({"cell": "0", "micro_community": "CJ", "gender": "M", "Outcome": "Yes"} for _ in range(4))
    rows.extend({"cell": "1", "micro_community": "CJ", "gender": "F", "Outcome": "No"} for _ in range(4))
    return pd.DataFrame(rows)


def _question_metadata() -> list[dict[str, object]]:
    """Return minimal metadata for the weighting scenario."""
    return [
        {
            "variable": "cell",
            "display_variable_name": "Cell",
            "question_label": "Cell",
            "detected_type": "Ignore",
            "answer_choices_list": ["Control", "Test"],
            "include": False,
        },
        {
            "variable": "micro_community",
            "display_variable_name": "Micro Community",
            "question_label": "Micro Community",
            "detected_type": "Single-Select",
            "answer_choices_list": ["AO", "CJ", "TL"],
            "include": False,
        },
        {
            "variable": "gender",
            "display_variable_name": "Gender",
            "question_label": "Gender",
            "detected_type": "Single-Select",
            "answer_choices_list": ["M", "F"],
            "include": False,
        },
        {
            "variable": "Outcome",
            "display_variable_name": "Outcome",
            "question_label": "Outcome",
            "detected_type": "Single-Select",
            "answer_choices_list": ["Yes", "No"],
            "include": True,
        },
    ]


def _stat_config() -> dict[str, object]:
    """Return stat settings with percentages only for easier assertions."""
    return {
        "enabled": False,
        "comparison_scope": "none",
        "confidence_intervals": [95],
        "include_percentage": True,
        "include_n_count": True,
    }


def _weighting_config() -> dict[str, object]:
    """Return a config that balances comparison groups to the total gender mix."""
    return {
        "weights": [
            {
                "name": "Gender balance",
                "target": "Match cell groups",
                "source": "",
                "variables": ["gender"],
                "applies_to": ["All Tables"],
            }
        ]
    }


def _tl_limited_weighting_config() -> dict[str, object]:
    """Return a config that balances only TL cell groups on gender."""
    return {
        "weights": [
            {
                "name": "TL Gender balance",
                "target": "Match cell groups",
                "source": "",
                "variables": ["gender"],
                "limit_variable": "micro_community",
                "limit_values": ["TL"],
                "applies_to": ["All Tables"],
            }
        ]
    }


def _tl_custom_weighting_config() -> dict[str, object]:
    """Return a config that balances TL cell groups to custom gender percentages."""
    return {
        "weights": [
            {
                "name": "TL Custom Gender balance",
                "target": "Custom percentages",
                "source": "",
                "variables": ["gender"],
                "limit_variable": "micro_community",
                "limit_values": ["TL"],
                "custom_targets": {"M": 25.0, "F": 75.0},
                "applies_to": ["All Tables"],
            }
        ]
    }


def _tl_stacked_weighting_config() -> dict[str, object]:
    """Return a config with two TL-limited weight rows that should stack."""
    return {
        "weights": [
            {
                "name": "TL Gender balance",
                "target": "Match cell groups",
                "source": "",
                "variables": ["gender"],
                "limit_variable": "micro_community",
                "limit_values": ["TL"],
                "applies_to": ["All Tables"],
            },
            {
                "name": "TL Outcome balance",
                "target": "Custom percentages",
                "source": "",
                "variables": ["Outcome"],
                "limit_variable": "micro_community",
                "limit_values": ["TL"],
                "custom_targets": {"Yes": 40.0, "No": 60.0},
                "applies_to": ["All Tables"],
            },
        ]
    }


def _package(weighting_config: dict[str, object]) -> dict[str, object]:
    """Generate a workbook package for the weighting scenario."""
    return generate_workbook_package(
        cleaned_df=_weighted_dataframe(),
        question_metadata=_question_metadata(),
        custom_variables=[],
        banner_config={
            "banners": [{"name": "Cells", "level_1": "cell", "level_2": "", "level_3": ""}],
            "include_total": True,
            "export_style": "one_per_sheet",
        },
        adhoc_crosstabs_config={"tables": []},
        net_definitions={},
        scale_mappings={},
        banner_stat_config=_stat_config(),
        adhoc_stat_config=_stat_config(),
        comparison_col="cell",
        comparison_group_order={},
        comparison_group_labels={},
        comparison_scheme={},
        global_filters={"rows": []},
        weighting_config=weighting_config,
        topline_config={"configured": False},
    )


def _unequal_package(weighting_config: dict[str, object]) -> dict[str, object]:
    """Generate a workbook package where source groups have different sizes."""
    return generate_workbook_package(
        cleaned_df=_unequal_weighted_dataframe(),
        question_metadata=_question_metadata(),
        custom_variables=[],
        banner_config={
            "banners": [{"name": "Cells", "level_1": "cell", "level_2": "", "level_3": ""}],
            "include_total": True,
            "export_style": "one_per_sheet",
        },
        adhoc_crosstabs_config={"tables": []},
        net_definitions={},
        scale_mappings={},
        banner_stat_config=_stat_config(),
        adhoc_stat_config=_stat_config(),
        comparison_col="cell",
        comparison_group_order={},
        comparison_group_labels={},
        comparison_scheme={},
        global_filters={"rows": []},
        weighting_config=weighting_config,
        topline_config={"configured": False},
    )


def _micro_package(weighting_config: dict[str, object]) -> dict[str, object]:
    """Generate a workbook package for the TL-limited weighting scenario."""
    return generate_workbook_package(
        cleaned_df=_micro_community_dataframe(),
        question_metadata=_question_metadata(),
        custom_variables=[],
        banner_config={
            "banners": [{"name": "Micro Community", "level_1": "micro_community", "level_2": "cell", "level_3": ""}],
            "include_total": True,
            "export_style": "one_per_sheet",
        },
        adhoc_crosstabs_config={"tables": []},
        net_definitions={},
        scale_mappings={},
        banner_stat_config=_stat_config(),
        adhoc_stat_config=_stat_config(),
        comparison_col="cell",
        comparison_group_order={},
        comparison_group_labels={},
        comparison_scheme={},
        global_filters={"rows": []},
        weighting_config=weighting_config,
        topline_config={"configured": False},
    )


def _yes_percentages(package: dict[str, object]) -> dict[str, float]:
    """Return the Total Answering Yes percentage by group label."""
    sheet = package["sheets"][0]
    table = next(table for table in sheet.tables if table.variable == "Outcome")
    group_labels = [group["label"] for group in table.groups]
    section = next(section for section in table.sections if section["label"] == "Total Answering")
    yes_row = next(row for row in section["rows"] if row["label"] == "Yes")
    return dict(zip(group_labels, yes_row["percentages"]))


def _table_percentages_for_group(package: dict[str, object], group_label: str) -> float:
    """Return the Total Answering Yes percentage for one banner group."""
    sheet = package["sheets"][0]
    table = next(table for table in sheet.tables if table.variable == "Outcome")
    group_labels = [group["label"] for group in table.groups]
    group_index = group_labels.index(group_label)
    section = next(section for section in table.sections if section["label"] == "Total Answering")
    yes_row = next(row for row in section["rows"] if row["label"] == "Yes")
    return yes_row["percentages"][group_index]


class WeightingTest(unittest.TestCase):
    def test_weighting_balances_percentages_to_target_distribution(self) -> None:
        unweighted = _yes_percentages(_package({"weights": []}))
        weighted_package = _package(_weighting_config())
        weighted = _yes_percentages(weighted_package)

        self.assertAlmostEqual(unweighted["Control"], 0.9)
        self.assertAlmostEqual(unweighted["Test"], 0.1)
        self.assertAlmostEqual(weighted["Control"], 0.5)
        self.assertAlmostEqual(weighted["Test"], 0.5)
        self.assertIn("Weighting applied: Gender balance", weighted_package["sheets"][0].footnotes)

    def test_match_groups_target_uses_equal_average_across_source_groups(self) -> None:
        weighted = _yes_percentages(_unequal_package(_weighting_config()))

        self.assertAlmostEqual(weighted["Control"], 0.5)
        self.assertAlmostEqual(weighted["Test"], 0.5)

    def test_weight_audit_dataframe_exports_per_respondent_factors(self) -> None:
        audit_df = build_weighted_respondent_export_dataframe(
            _weighted_dataframe(),
            _question_metadata(),
            custom_variables=[],
            net_definitions={},
            scale_mappings={},
            weighting_config=_weighting_config(),
            comparison_col="cell",
        )

        self.assertIn("BLS_Weight_Gender_balance", audit_df.columns)
        self.assertIn(FINAL_WEIGHT_COLUMN, audit_df.columns)
        control_m = audit_df[(audit_df["cell"] == "Control") & (audit_df["gender"] == "M")].iloc[0]
        control_f = audit_df[(audit_df["cell"] == "Control") & (audit_df["gender"] == "F")].iloc[0]
        self.assertAlmostEqual(control_m["BLS_Weight_Gender_balance"], 0.555556)
        self.assertAlmostEqual(control_f["BLS_Weight_Gender_balance"], 5.0)
        self.assertAlmostEqual(control_m[FINAL_WEIGHT_COLUMN], 0.555556)

    def test_weighting_limit_only_adjusts_matching_respondents(self) -> None:
        audit_df = build_weighted_respondent_export_dataframe(
            _micro_community_dataframe(),
            _question_metadata(),
            custom_variables=[],
            net_definitions={},
            scale_mappings={},
            weighting_config=_tl_limited_weighting_config(),
            comparison_col="cell",
        )

        self.assertIn("BLS_Weight_TL_Gender_balance", audit_df.columns)
        non_tl = audit_df[audit_df["micro_community"] != "TL"]
        self.assertTrue((non_tl["BLS_Weight_TL_Gender_balance"] == 1.0).all())
        self.assertTrue((non_tl[FINAL_WEIGHT_COLUMN] == 1.0).all())

        tl_control_m = audit_df[
            (audit_df["micro_community"] == "TL")
            & (audit_df["cell"] == "0")
            & (audit_df["gender"] == "M")
        ].iloc[0]
        tl_control_f = audit_df[
            (audit_df["micro_community"] == "TL")
            & (audit_df["cell"] == "0")
            & (audit_df["gender"] == "F")
        ].iloc[0]
        self.assertAlmostEqual(tl_control_m["BLS_Weight_TL_Gender_balance"], 0.555556)
        self.assertAlmostEqual(tl_control_f["BLS_Weight_TL_Gender_balance"], 5.0)

    def test_multiple_weight_rows_stack_into_final_weight(self) -> None:
        audit_df = build_weighted_respondent_export_dataframe(
            _micro_community_dataframe(),
            _question_metadata(),
            custom_variables=[],
            net_definitions={},
            scale_mappings={},
            weighting_config=_tl_stacked_weighting_config(),
            comparison_col="cell",
        )

        self.assertIn("BLS_Weight_TL_Gender_balance", audit_df.columns)
        self.assertIn("BLS_Weight_TL_Outcome_balance", audit_df.columns)
        expected_final_weight = audit_df["BLS_Weight_TL_Gender_balance"] * audit_df["BLS_Weight_TL_Outcome_balance"]
        self.assertTrue(((audit_df[FINAL_WEIGHT_COLUMN] - expected_final_weight).abs() < 0.00001).all())

    def test_weighting_limit_balances_only_tl_table_groups(self) -> None:
        unweighted = _micro_package({"weights": []})
        weighted = _micro_package(_tl_limited_weighting_config())

        self.assertAlmostEqual(_table_percentages_for_group(unweighted, "TL | 0"), 0.9)
        self.assertAlmostEqual(_table_percentages_for_group(unweighted, "TL | 1"), 0.1)
        self.assertAlmostEqual(_table_percentages_for_group(weighted, "TL | 0"), 0.5)
        self.assertAlmostEqual(_table_percentages_for_group(weighted, "TL | 1"), 0.5)
        self.assertAlmostEqual(_table_percentages_for_group(weighted, "AO | 0"), 1.0)
        self.assertAlmostEqual(_table_percentages_for_group(weighted, "AO | 1"), 0.0)

    def test_custom_percentage_target_balances_limited_groups(self) -> None:
        weighted = _micro_package(_tl_custom_weighting_config())

        self.assertAlmostEqual(_table_percentages_for_group(weighted, "TL | 0"), 0.25)
        self.assertAlmostEqual(_table_percentages_for_group(weighted, "TL | 1"), 0.25)
        self.assertAlmostEqual(_table_percentages_for_group(weighted, "AO | 0"), 1.0)
        self.assertAlmostEqual(_table_percentages_for_group(weighted, "AO | 1"), 0.0)


if __name__ == "__main__":
    unittest.main()

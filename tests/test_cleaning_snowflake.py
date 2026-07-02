"""Regression checks for Snowflake survey intake."""

from __future__ import annotations

import unittest

import pandas as pd

from app.services.legacy_flow import (
    _apply_snowflake_display_variable_names,
    _build_filter_value_display_labels,
    _build_filter_value_options,
    _build_included_editor,
    _included_editor_widget_key,
    _layered_condition_default_values,
    _order_question_metadata_by_columns,
    _reorder_included_question_rows,
    _sync_question_metadata_from_intake_labels,
    _valid_multiselect_values,
)
from src.cleaning import (
    _MULTI_SELECT_DELIMITER,
    _is_snowflake_long_format,
    _pivot_snowflake_long_to_wide,
    ingest_snowflake_dataframe,
)
from src.metadata import (
    _is_multi_select,
    build_question_metadata,
    prepare_metadata_editor_frame,
    sanitize_metadata_editor,
)
from src.respondents import RESPONDENT_ID_COLUMN, respondent_count
from src.tables import _build_question_table


def _standard_long_df() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "SURVEY_RESPONSE_ID": "R001",
                "QUESTION_KEY": "Q1",
                "QUESTION_TEXT": "Favorite color? - Label",
                "BLOCK_DESCRIPTION": "Color preference",
                "QUESTION_OPTION_TEXT": "Blue",
            },
            {
                "SURVEY_RESPONSE_ID": "R001",
                "QUESTION_KEY": "cell",
                "QUESTION_TEXT": "Comparison Group",
                "QUESTION_OPTION_TEXT": "Control",
            },
            {
                "SURVEY_RESPONSE_ID": "R002",
                "QUESTION_KEY": "Q1",
                "QUESTION_TEXT": "Favorite color? - Label",
                "BLOCK_DESCRIPTION": "Color preference",
                "QUESTION_OPTION_TEXT": "Red",
            },
            {
                "SURVEY_RESPONSE_ID": "R002",
                "QUESTION_KEY": "cell",
                "QUESTION_TEXT": "Comparison Group",
                "QUESTION_OPTION_TEXT": "Test",
            },
        ]
    )


def _matrix_scale_long_df() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "RESPONSE_KEY": "RESP_A",
                "QUESTION_KEY": "QID17",
                "QUESTION_TEXT": "How much do you agree with each statement? - Label",
                "BLOCK_DESCRIPTION": "Brand Perception",
                "SUB_QUESTION_KEY": "1",
                "SUB_QUESTION_TEXT": "The brand is innovative",
                "QUESTION_OPTION_TEXT": "Strongly agree",
            },
            {
                "RESPONSE_KEY": "RESP_A",
                "QUESTION_KEY": "QID17",
                "QUESTION_TEXT": "How much do you agree with each statement? - Label",
                "BLOCK_DESCRIPTION": "Brand Perception",
                "SUB_QUESTION_KEY": "2",
                "SUB_QUESTION_TEXT": "The brand is trustworthy",
                "QUESTION_OPTION_TEXT": "Disagree",
            },
            {
                "RESPONSE_KEY": "RESP_B",
                "QUESTION_KEY": "QID17",
                "QUESTION_TEXT": "How much do you agree with each statement? - Label",
                "BLOCK_DESCRIPTION": "Brand Perception",
                "SUB_QUESTION_KEY": "1",
                "SUB_QUESTION_TEXT": "The brand is innovative",
                "QUESTION_OPTION_TEXT": "Agree",
            },
            {
                "RESPONSE_KEY": "RESP_B",
                "QUESTION_KEY": "QID17",
                "QUESTION_TEXT": "How much do you agree with each statement? - Label",
                "BLOCK_DESCRIPTION": "Brand Perception",
                "SUB_QUESTION_KEY": "2",
                "SUB_QUESTION_TEXT": "The brand is trustworthy",
                "QUESTION_OPTION_TEXT": "Neutral",
            },
            {
                "RESPONSE_KEY": "RESP_C",
                "QUESTION_KEY": "QID17",
                "QUESTION_TEXT": "How much do you agree with each statement? - Label",
                "BLOCK_DESCRIPTION": "Brand Perception",
                "SUB_QUESTION_KEY": "1",
                "SUB_QUESTION_TEXT": "The brand is innovative",
                "QUESTION_OPTION_TEXT": "Neutral",
            },
            {
                "RESPONSE_KEY": "RESP_C",
                "QUESTION_KEY": "QID17",
                "QUESTION_TEXT": "How much do you agree with each statement? - Label",
                "BLOCK_DESCRIPTION": "Brand Perception",
                "SUB_QUESTION_KEY": "2",
                "SUB_QUESTION_TEXT": "The brand is trustworthy",
                "QUESTION_OPTION_TEXT": "Strongly disagree",
            },
        ]
    )


class SnowflakeLongFormatTest(unittest.TestCase):
    def test_detects_required_columns_case_insensitively(self) -> None:
        df = pd.DataFrame(
            {
                "survey_response_id": ["R001"],
                "question_key": ["Q1"],
                "question_option_text": ["Yes"],
            }
        )

        self.assertTrue(_is_snowflake_long_format(df))

    def test_wide_dataframe_is_not_detected_as_long_format(self) -> None:
        df = pd.DataFrame({"respondent_id": ["R001"], "Q1": ["Yes"], "cell": ["Control"]})

        self.assertFalse(_is_snowflake_long_format(df))

    def test_pivot_returns_one_row_per_respondent(self) -> None:
        wide_df, labels = _pivot_snowflake_long_to_wide(_standard_long_df())

        self.assertEqual(len(wide_df), 2)
        self.assertEqual(set(wide_df.columns), {RESPONDENT_ID_COLUMN, "Q1", "cell"})
        self.assertEqual(labels["Q1"], "Color preference")
        self.assertEqual(labels["cell"], "Comparison Group")
        self.assertEqual(wide_df[RESPONDENT_ID_COLUMN].tolist(), ["R001", "R002"])

    def test_pivot_keeps_duplicate_response_ids_from_different_surveys_separate(self) -> None:
        df = pd.DataFrame(
            [
                {
                    "SURVEY_KEY": "SV_A",
                    "SURVEY_RESPONSE_ID": "R001",
                    "QUESTION_KEY": "Q1",
                    "QUESTION_OPTION_TEXT": "Blue",
                },
                {
                    "SURVEY_KEY": "SV_B",
                    "SURVEY_RESPONSE_ID": "R001",
                    "QUESTION_KEY": "Q1",
                    "QUESTION_OPTION_TEXT": "Red",
                },
            ]
        )

        wide_df, _ = _pivot_snowflake_long_to_wide(df)

        self.assertEqual(len(wide_df), 2)
        self.assertEqual(wide_df["Q1"].tolist(), ["Blue", "Red"])
        self.assertEqual(wide_df[RESPONDENT_ID_COLUMN].tolist(), ["SV_A::R001", "SV_B::R001"])

    def test_pivot_prefers_response_key_for_respondent_identity(self) -> None:
        df = pd.DataFrame(
            [
                {
                    "SURVEY_RESPONSE_ID": "ROW_001",
                    "RESPONSE_KEY": "RESP_A",
                    "QUESTION_KEY": "Q1",
                    "QUESTION_OPTION_TEXT": "Blue",
                },
                {
                    "SURVEY_RESPONSE_ID": "ROW_002",
                    "RESPONSE_KEY": "RESP_A",
                    "QUESTION_KEY": "cell",
                    "QUESTION_OPTION_TEXT": "Control",
                },
                {
                    "SURVEY_RESPONSE_ID": "ROW_003",
                    "RESPONSE_KEY": "RESP_B",
                    "QUESTION_KEY": "Q1",
                    "QUESTION_OPTION_TEXT": "Red",
                },
                {
                    "SURVEY_RESPONSE_ID": "ROW_004",
                    "RESPONSE_KEY": "RESP_B",
                    "QUESTION_KEY": "cell",
                    "QUESTION_OPTION_TEXT": "Test",
                },
            ]
        )

        wide_df, _ = _pivot_snowflake_long_to_wide(df)

        self.assertEqual(len(wide_df), 2)
        self.assertEqual(wide_df[RESPONDENT_ID_COLUMN].tolist(), ["RESP_A", "RESP_B"])
        self.assertEqual(wide_df["Q1"].tolist(), ["Blue", "Red"])
        self.assertEqual(wide_df["cell"].tolist(), ["Control", "Test"])

    def test_pivot_prefers_qualtrics_rid_over_snowflake_row_id(self) -> None:
        df = pd.DataFrame(
            [
                {
                    "SURVEY_RESPONSE_ID": "ROW_001",
                    "RID": "RID_A",
                    "QUESTION_KEY": "Q1",
                    "QUESTION_OPTION_TEXT": "Blue",
                },
                {
                    "SURVEY_RESPONSE_ID": "ROW_002",
                    "RID": "RID_A",
                    "QUESTION_KEY": "cell",
                    "QUESTION_OPTION_TEXT": "Control",
                },
                {
                    "SURVEY_RESPONSE_ID": "ROW_003",
                    "RID": "RID_B",
                    "QUESTION_KEY": "Q1",
                    "QUESTION_OPTION_TEXT": "Red",
                },
                {
                    "SURVEY_RESPONSE_ID": "ROW_004",
                    "RID": "RID_B",
                    "QUESTION_KEY": "cell",
                    "QUESTION_OPTION_TEXT": "Test",
                },
            ]
        )

        wide_df, _ = _pivot_snowflake_long_to_wide(df)

        self.assertEqual(len(wide_df), 2)
        self.assertEqual(wide_df[RESPONDENT_ID_COLUMN].tolist(), ["RID_A", "RID_B"])
        self.assertEqual(wide_df["Q1"].tolist(), ["Blue", "Red"])
        self.assertEqual(wide_df["cell"].tolist(), ["Control", "Test"])

    def test_pivot_uses_embedded_rid_for_respondent_counting(self) -> None:
        df = pd.DataFrame(
            [
                {
                    "SURVEY_RESPONSE_ID": "R001",
                    "QUESTION_KEY": "Q1",
                    "QUESTION_OPTION_TEXT": "Blue",
                    "EMBEDDED_DATA_KEY": "rid",
                    "EMBEDDED_DATA_VALUE": "RID_A",
                },
                {
                    "SURVEY_RESPONSE_ID": "R002",
                    "QUESTION_KEY": "Q1",
                    "QUESTION_OPTION_TEXT": "Red",
                    "EMBEDDED_DATA_KEY": "rid",
                    "EMBEDDED_DATA_VALUE": "RID_A",
                },
            ]
        )

        result = ingest_snowflake_dataframe(df, source_name="RID embedded")

        self.assertEqual(respondent_count(result.cleaned_df), 1)
        self.assertNotIn("rid", result.cleaned_df.columns)

    def test_pivot_preserves_repeated_respondent_level_embedded_columns(self) -> None:
        df = pd.DataFrame(
            [
                {
                    "SURVEY_RESPONSE_ID": "R001",
                    "SURVEY_NAME": "Study",
                    "QUESTION_KEY": "Q1",
                    "QUESTION_OPTION_TEXT": "Blue",
                    "BRAND": "Acme",
                    "COUNTRY": "US",
                },
                {
                    "SURVEY_RESPONSE_ID": "R001",
                    "SURVEY_NAME": "Study",
                    "QUESTION_KEY": "Q2",
                    "QUESTION_OPTION_TEXT": "Yes",
                    "BRAND": "Acme",
                    "COUNTRY": "US",
                },
                {
                    "SURVEY_RESPONSE_ID": "R002",
                    "SURVEY_NAME": "Study",
                    "QUESTION_KEY": "Q1",
                    "QUESTION_OPTION_TEXT": "Red",
                    "BRAND": "Acme",
                    "COUNTRY": "CA",
                },
            ]
        )

        wide_df, labels = _pivot_snowflake_long_to_wide(df)

        self.assertEqual(wide_df["BRAND"].tolist(), ["Acme", "Acme"])
        self.assertEqual(wide_df["COUNTRY"].tolist(), ["US", "CA"])
        self.assertNotIn("SURVEY_NAME", wide_df.columns)
        self.assertEqual(labels["BRAND"], "Brand")
        self.assertEqual(labels["COUNTRY"], "Country")

    def test_pivot_preserves_key_value_embedded_variables(self) -> None:
        df = pd.DataFrame(
            [
                {
                    "SURVEY_RESPONSE_ID": "R001",
                    "QUESTION_KEY": "Q1",
                    "QUESTION_OPTION_TEXT": "Blue",
                    "EMBEDDED_DATA_KEY": "campaign_name",
                    "EMBEDDED_DATA_VALUE": "Launch",
                },
                {
                    "SURVEY_RESPONSE_ID": "R002",
                    "QUESTION_KEY": "Q1",
                    "QUESTION_OPTION_TEXT": "Red",
                    "EMBEDDED_DATA_KEY": "campaign_name",
                    "EMBEDDED_DATA_VALUE": "Evergreen",
                },
            ]
        )

        wide_df, labels = _pivot_snowflake_long_to_wide(df)

        self.assertEqual(wide_df["campaign_name"].tolist(), ["Launch", "Evergreen"])
        self.assertEqual(labels["campaign_name"], "Campaign Name")

    def test_pivot_expands_embedded_data_json_variables(self) -> None:
        df = pd.DataFrame(
            [
                {
                    "RESPONSE_KEY": "RESP_A",
                    "SURVEY_RESPONSE_ID": "ROW_001",
                    "QUESTION_KEY": "Q1",
                    "QUESTION_OPTION_TEXT": "Blue",
                    "EMBEDDED_DATA": '{"campaign_name":"Launch","audience_id":"A1","gc":"1","rid":"RID_A"}',
                },
                {
                    "RESPONSE_KEY": "RESP_B",
                    "SURVEY_RESPONSE_ID": "ROW_002",
                    "QUESTION_KEY": "Q1",
                    "QUESTION_OPTION_TEXT": "Red",
                    "EMBEDDED_DATA": '{"campaign_name":"Evergreen","audience_id":"A2","gc":"1","rid":"RID_B"}',
                },
            ]
        )

        wide_df, labels = _pivot_snowflake_long_to_wide(df)

        self.assertEqual(wide_df["campaign_name"].tolist(), ["Launch", "Evergreen"])
        self.assertEqual(wide_df["audience_id"].tolist(), ["A1", "A2"])
        self.assertEqual(labels["campaign_name"], "Campaign Name")
        self.assertEqual(labels["audience_id"], "Audience Id")
        self.assertNotIn("EMBEDDED_DATA", wide_df.columns)

    def test_multi_select_values_are_collapsed_with_supported_delimiter(self) -> None:
        df = pd.DataFrame(
            [
                {
                    "SURVEY_RESPONSE_ID": "R001",
                    "QUESTION_KEY": "Q_MS",
                    "QUESTION_TEXT": "Select all that apply",
                    "QUESTION_OPTION_TEXT": "Option A",
                },
                {
                    "SURVEY_RESPONSE_ID": "R001",
                    "QUESTION_KEY": "Q_MS",
                    "QUESTION_TEXT": "Select all that apply",
                    "QUESTION_OPTION_TEXT": "Option C",
                },
                {
                    "SURVEY_RESPONSE_ID": "R002",
                    "QUESTION_KEY": "Q_MS",
                    "QUESTION_TEXT": "Select all that apply",
                    "QUESTION_OPTION_TEXT": "Option B",
                },
                {
                    "SURVEY_RESPONSE_ID": "R002",
                    "QUESTION_KEY": "Q_MS",
                    "QUESTION_TEXT": "Select all that apply",
                    "QUESTION_OPTION_TEXT": "Option C",
                },
            ]
        )

        wide_df, _ = _pivot_snowflake_long_to_wide(df)

        self.assertIn(_MULTI_SELECT_DELIMITER, wide_df["Q_MS"].iloc[0])
        self.assertTrue(_is_multi_select(wide_df["Q_MS"]))

    def test_matrix_scale_sub_questions_pivot_to_statement_columns(self) -> None:
        wide_df, labels = _pivot_snowflake_long_to_wide(_matrix_scale_long_df())

        self.assertIn("QID17_1", wide_df.columns)
        self.assertIn("QID17_2", wide_df.columns)
        self.assertNotIn("QID17", wide_df.columns)
        self.assertEqual(wide_df["QID17_1"].tolist(), ["Strongly agree", "Agree", "Neutral"])
        self.assertEqual(wide_df["QID17_2"].tolist(), ["Disagree", "Neutral", "Strongly disagree"])
        self.assertEqual(labels["QID17_1"], "The brand is innovative (Brand Perception)")
        self.assertEqual(labels["QID17_2"], "The brand is trustworthy (Brand Perception)")
        self.assertEqual(
            wide_df.attrs["question_text_labels"]["QID17_1"],
            "How much do you agree with each statement? - The brand is innovative",
        )

    def test_long_format_detects_response_key_and_answer_text_without_option_text(self) -> None:
        df = pd.DataFrame(
            {
                "RESPONSE_KEY": ["RESP_A"],
                "QUESTION_KEY": ["QID1"],
                "ANSWER_TEXT": ["Yes"],
            }
        )

        self.assertTrue(_is_snowflake_long_format(df))

    def test_matrix_scale_numeric_sub_keys_do_not_keep_float_suffixes(self) -> None:
        df = _matrix_scale_long_df()
        df["SUB_QUESTION_KEY"] = df["SUB_QUESTION_KEY"].astype(float)

        wide_df, _ = _pivot_snowflake_long_to_wide(df)

        self.assertIn("QID17_1", wide_df.columns)
        self.assertIn("QID17_2", wide_df.columns)
        self.assertNotIn("QID17_1.0", wide_df.columns)


class SnowflakeIngestionTest(unittest.TestCase):
    def test_ingestion_preserves_app_result_shape(self) -> None:
        result = ingest_snowflake_dataframe(_standard_long_df(), source_name="Study A")

        self.assertEqual(len(result.cleaned_df), 2)
        self.assertIn(RESPONDENT_ID_COLUMN, result.cleaned_df.columns)
        self.assertEqual(result.cell_column, "cell")
        self.assertEqual(result.sheet_name, "Snowflake")
        self.assertEqual(result.question_labels["Q1"], "Color preference")
        self.assertEqual(result.question_text_labels["Q1"], "Favorite color?")
        self.assertEqual(result.question_text_labels["cell"], "Comparison Group")
        self.assertEqual(result.source_answer_choices, {})
        self.assertTrue(any("respondent" in line.lower() for line in result.log_lines))

    def test_snowflake_question_text_removes_label_suffix_without_block_description(self) -> None:
        result = ingest_snowflake_dataframe(
            pd.DataFrame(
                [
                    {
                        "SURVEY_RESPONSE_ID": "R001",
                        "QUESTION_KEY": "Q1",
                        "QUESTION_TEXT": "How old are you? - Label",
                        "QUESTION_OPTION_TEXT": "25-34",
                    }
                ]
            ),
            source_name="LabelSuffix",
        )

        self.assertEqual(result.question_labels["Q1"], "How old are you?")
        self.assertEqual(result.question_text_labels["Q1"], "How old are you?")

    def test_wide_snowflake_dataframe_passes_through(self) -> None:
        result = ingest_snowflake_dataframe(
            pd.DataFrame(
                {
                    "cell": ["Control", "Test"],
                    "Q1": ["Yes", "No"],
                }
            ),
            source_name="AlreadyWide",
        )

        self.assertEqual(
            [column for column in result.cleaned_df.columns if column != RESPONDENT_ID_COLUMN],
            ["cell", "Q1"],
        )
        self.assertEqual(result.cell_column, "cell")
        self.assertEqual(result.question_labels["Q1"], "Q1")

    def test_wide_snowflake_dataframe_uses_unique_respondent_id_for_counts(self) -> None:
        result = ingest_snowflake_dataframe(
            pd.DataFrame(
                {
                    "SURVEY_RESPONSE_ID": ["ROW_1", "ROW_2", "ROW_3"],
                    "RESPONSE_KEY": ["RESP_A", "RESP_A", "RESP_B"],
                    "RID": ["RID_A", "RID_A", "RID_B"],
                    "cell": ["Control", "Control", "Test"],
                    "Q1": ["Yes", "Yes", "No"],
                }
            ),
            source_name="WideWithRespondentIds",
        )

        self.assertIn(RESPONDENT_ID_COLUMN, result.cleaned_df.columns)
        self.assertNotIn("SURVEY_RESPONSE_ID", result.cleaned_df.columns)
        self.assertNotIn("RESPONSE_KEY", result.cleaned_df.columns)
        self.assertNotIn("RID", result.cleaned_df.columns)
        self.assertEqual(respondent_count(result.cleaned_df), 2)

    def test_snowflake_metadata_columns_default_to_excluded(self) -> None:
        result = ingest_snowflake_dataframe(
            pd.DataFrame(
                [
                    {
                        "RESPONSE_KEY": "RESP_A",
                        "SURVEY_RESPONSE_ID": "ROW_001",
                        "QUESTION_KEY": "Q1",
                        "QUESTION_OPTION_TEXT": "Blue",
                        "START_DATE": "2026-01-01",
                        "END_DATETIME": "2026-01-01 00:10:00",
                        "DURATION_IN_SECONDS": 600,
                        "IS_FINISHED": True,
                        "USER_LANGUAGE": "EN",
                        "LOCATION_LATITUDE": 40.0,
                    },
                    {
                        "RESPONSE_KEY": "RESP_B",
                        "SURVEY_RESPONSE_ID": "ROW_002",
                        "QUESTION_KEY": "Q1",
                        "QUESTION_OPTION_TEXT": "Red",
                        "START_DATE": "2026-01-02",
                        "END_DATETIME": "2026-01-02 00:10:00",
                        "DURATION_IN_SECONDS": 620,
                        "IS_FINISHED": True,
                        "USER_LANGUAGE": "EN",
                        "LOCATION_LATITUDE": 41.0,
                    },
                ]
            ),
            source_name="MetadataDefaults",
        )

        self.assertIn("Q1", result.cleaned_df.columns)
        for column in [
            "START_DATE",
            "END_DATETIME",
            "DURATION_IN_SECONDS",
            "IS_FINISHED",
            "USER_LANGUAGE",
            "LOCATION_LATITUDE",
        ]:
            self.assertNotIn(column, result.cleaned_df.columns)
            self.assertIn(column, result.removed_columns)

    def test_embedded_data_json_metadata_is_excluded_but_custom_keys_remain(self) -> None:
        result = ingest_snowflake_dataframe(
            pd.DataFrame(
                [
                    {
                        "RESPONSE_KEY": "RESP_A",
                        "SURVEY_RESPONSE_ID": "ROW_001",
                        "QUESTION_KEY": "Q1",
                        "QUESTION_OPTION_TEXT": "Blue",
                        "EMBEDDED_DATA": '{"campaign_name":"Launch","audience_id":"A1","gc":"1","rid":"RID_A","Q_DuplicateRespondent":""}',
                    },
                    {
                        "RESPONSE_KEY": "RESP_B",
                        "SURVEY_RESPONSE_ID": "ROW_002",
                        "QUESTION_KEY": "Q1",
                        "QUESTION_OPTION_TEXT": "Red",
                        "EMBEDDED_DATA": '{"campaign_name":"Evergreen","audience_id":"A2","gc":"1","rid":"RID_B","Q_DuplicateRespondent":""}',
                    },
                ]
            ),
            source_name="EmbeddedJson",
        )

        self.assertIn("campaign_name", result.cleaned_df.columns)
        self.assertIn("audience_id", result.cleaned_df.columns)
        self.assertNotIn("EMBEDDED_DATA", result.cleaned_df.columns)
        self.assertNotIn("gc", result.cleaned_df.columns)
        self.assertNotIn("rid", result.cleaned_df.columns)
        self.assertNotIn("Q_DuplicateRespondent", result.cleaned_df.columns)
        self.assertIn("gc", result.removed_columns)
        self.assertIn("rid", result.removed_columns)
        self.assertIn("Q_DuplicateRespondent", result.removed_columns)

    def test_internal_respondent_id_is_not_question_metadata(self) -> None:
        result = ingest_snowflake_dataframe(_standard_long_df(), source_name="Study A")
        metadata = build_question_metadata(
            result.cleaned_df,
            result.question_labels,
            result.cell_column,
            result.source_answer_choices,
        )

        self.assertNotIn(RESPONDENT_ID_COLUMN, [row["variable"] for row in metadata])

    def test_matrix_scale_metadata_matches_statement_level_file_exports(self) -> None:
        result = ingest_snowflake_dataframe(_matrix_scale_long_df(), source_name="Matrix Scale")
        metadata = build_question_metadata(
            result.cleaned_df,
            result.question_text_labels,
            result.cell_column,
            result.source_answer_choices,
        )
        _apply_snowflake_display_variable_names(metadata, result.question_labels)
        rows_by_variable = {row["variable"]: row for row in metadata}

        self.assertEqual(set(rows_by_variable), {"QID17_1", "QID17_2"})
        self.assertEqual(rows_by_variable["QID17_1"]["detected_type"], "Scale / Likert")
        self.assertEqual(rows_by_variable["QID17_2"]["detected_type"], "Scale / Likert")
        self.assertEqual(
            rows_by_variable["QID17_1"]["display_variable_name"],
            "The brand is innovative (Brand Perception)",
        )
        self.assertEqual(
            rows_by_variable["QID17_1"]["question_label"],
            "How much do you agree with each statement? - The brand is innovative",
        )


class SnowflakeFriendlyLabelTest(unittest.TestCase):
    def test_filter_value_options_remove_blank_choices(self) -> None:
        options = _build_filter_value_options(
            "CELL",
            {"CELL": {"answer_choices_list": ["", "Control", "Test", "Control"]}},
            [],
        )

        self.assertEqual(options, ["Control", "Test"])
        self.assertEqual(_valid_multiselect_values(["", "Control", "Missing"], options), ["Control"])

    def test_filter_value_display_labels_keep_raw_value_labels(self) -> None:
        labels = _build_filter_value_display_labels(
            "CELL",
            ["0", "1"],
            "CELL",
            {"0": "Control", "1": "Test"},
        )

        self.assertEqual(labels, {"0": "0", "1": "1"})

    def test_layered_cell_defaults_repair_blank_group_values(self) -> None:
        self.assertEqual(
            _layered_condition_default_values(
                ["", "Missing"],
                ["Control", "Test"],
                "CELL",
                "Control",
                "group_1",
                "CELL",
            ),
            ["Control"],
        )

    def test_included_editor_uses_question_text_as_visible_label(self) -> None:
        editor = _build_included_editor(
            ["QID12"],
            ["QID12"],
            {"QID12": "Testing overall satisfaction"},
        )
        row = editor.iloc[0].to_dict()

        self.assertEqual(row["Question / Variable"], "Testing overall satisfaction")
        self.assertEqual(row["Variable ID"], "QID12")
        self.assertEqual(row["_source_variables"], "QID12")

    def test_included_editor_uses_separate_snowflake_question_text(self) -> None:
        editor = _build_included_editor(
            ["QID12", "campaign_name"],
            ["QID12", "campaign_name"],
            {
                "QID12": "Satisfaction",
                "campaign_name": "Campaign Name",
            },
            {
                "QID12": "How satisfied are you overall?",
            },
        )
        rows = {
            row["Variable ID"]: row
            for row in editor.to_dict(orient="records")
        }

        self.assertEqual(rows["QID12"]["Question / Variable"], "Satisfaction")
        self.assertEqual(rows["QID12"]["Question Text"], "How satisfied are you overall?")
        self.assertEqual(rows["campaign_name"]["Question / Variable"], "Campaign Name")
        self.assertEqual(rows["campaign_name"]["Question Text"], "Campaign Name")

    def test_included_editor_sorts_by_variable_id_with_embeds_last(self) -> None:
        editor = _build_included_editor(
            ["campaign_name", "QID10", "audience_id", "QID2", "QID1"],
            ["campaign_name", "QID10", "audience_id", "QID2", "QID1"],
            {
                "QID1": "Question 1",
                "QID2": "Question 2",
                "QID10": "Question 10",
                "audience_id": "Audience Id",
                "campaign_name": "Campaign Name",
            },
        )

        self.assertEqual(
            editor["Variable ID"].tolist(),
            ["QID1", "QID2", "QID10", "audience_id", "campaign_name"],
        )

    def test_included_editor_respects_saved_question_order(self) -> None:
        editor = _build_included_editor(
            ["QID1", "QID2", "QID10", "campaign_name"],
            ["QID10", "QID2", "QID1", "campaign_name"],
            {
                "QID1": "Question 1",
                "QID2": "Question 2",
                "QID10": "Question 10",
                "campaign_name": "Campaign Name",
            },
            order_columns=["QID10", "QID2", "QID1", "campaign_name"],
        )

        self.assertEqual(
            editor["Variable ID"].tolist(),
            ["QID10", "QID2", "QID1", "campaign_name"],
        )

    def test_included_question_order_supports_top_and_bottom_moves(self) -> None:
        rows = [
            {"_order_key": "QID1", "_order_variables": ["QID1"]},
            {"_order_key": "QID2", "_order_variables": ["QID2"]},
            {"_order_key": "QID3", "_order_variables": ["QID3"]},
        ]

        moved_top = _reorder_included_question_rows(rows, "QID3", "top")
        moved_bottom = _reorder_included_question_rows(rows, "QID1", "bottom")

        self.assertEqual([row["_order_key"] for row in moved_top], ["QID3", "QID1", "QID2"])
        self.assertEqual([row["_order_key"] for row in moved_bottom], ["QID2", "QID3", "QID1"])

    def test_included_editor_widget_key_changes_when_order_changes(self) -> None:
        first_order = pd.DataFrame(
            [
                {"Variable ID": "QID1", "_source_variables": "QID1", "Included": True},
                {"Variable ID": "QID2", "_source_variables": "QID2", "Included": True},
            ]
        )
        second_order = pd.DataFrame(
            [
                {"Variable ID": "QID2", "_source_variables": "QID2", "Included": True},
                {"Variable ID": "QID1", "_source_variables": "QID1", "Included": True},
            ]
        )

        self.assertNotEqual(
            _included_editor_widget_key(first_order),
            _included_editor_widget_key(second_order),
        )

    def test_included_editor_lists_each_embedded_data_key(self) -> None:
        result = ingest_snowflake_dataframe(
            pd.DataFrame(
                [
                    {
                        "RESPONSE_KEY": "RESP_A",
                        "SURVEY_RESPONSE_ID": "ROW_001",
                        "QUESTION_KEY": "Q1",
                        "QUESTION_OPTION_TEXT": "Blue",
                        "EMBEDDED_DATA": '{"campaign_name":"Launch","audience_id":"A1"}',
                    }
                ]
            ),
            source_name="EmbeddedJson",
        )

        editor = _build_included_editor(
            list(result.cleaned_df.columns),
            list(result.cleaned_df.columns),
            result.question_labels,
            result.question_text_labels,
        )
        rows = editor.to_dict(orient="records")
        labels = {row["Question / Variable"]: row["Variable ID"] for row in rows}

        self.assertEqual(labels["Campaign Name"], "campaign_name")
        self.assertEqual(labels["Audience Id"], "audience_id")

    def test_page_three_editor_shows_display_label_and_keeps_source_variable(self) -> None:
        metadata_rows = [
            {
                "variable": "QID12",
                "display_variable_name": "Satisfaction",
                "question_label": "How satisfied are you overall?",
                "detected_type": "Single-Select",
                "answer_choices": "Yes | No",
                "answer_choices_list": ["Yes", "No"],
                "include": True,
                "notes": "",
            }
        ]

        editor = prepare_metadata_editor_frame(metadata_rows)
        row = editor.iloc[0].to_dict()

        self.assertEqual(row["variable"], "Satisfaction")
        self.assertEqual(row["_source_variable"], "QID12")
        self.assertEqual(row["question_label"], "How satisfied are you overall?")

        sanitized = sanitize_metadata_editor(editor)
        self.assertEqual(sanitized[0]["variable"], "QID12")
        self.assertEqual(sanitized[0]["display_variable_name"], "Satisfaction")
        self.assertEqual(sanitized[0]["question_label"], "How satisfied are you overall?")

    def test_page_three_metadata_syncs_from_page_two_labels(self) -> None:
        metadata_rows = [
            {
                "variable": "QID12",
                "display_variable_name": "QID12",
                "question_label": "Satisfaction",
                "detected_type": "Single-Select",
                "answer_choices": "Yes | No",
                "answer_choices_list": ["Yes", "No"],
                "include": True,
                "notes": "",
            }
        ]

        _sync_question_metadata_from_intake_labels(
            metadata_rows,
            ["QID12"],
            {"QID12": "Satisfaction"},
            {"QID12": "How satisfied are you overall?"},
        )

        self.assertEqual(metadata_rows[0]["display_variable_name"], "Satisfaction")
        self.assertEqual(metadata_rows[0]["question_label"], "How satisfied are you overall?")

    def test_page_three_metadata_sync_preserves_custom_display_name(self) -> None:
        metadata_rows = [
            {
                "variable": "QID12",
                "display_variable_name": "Overall Score",
                "question_label": "Satisfaction",
                "detected_type": "Single-Select",
                "answer_choices": "Yes | No",
                "answer_choices_list": ["Yes", "No"],
                "include": True,
                "notes": "",
            }
        ]

        _sync_question_metadata_from_intake_labels(
            metadata_rows,
            ["QID12"],
            {"QID12": "Satisfaction"},
            {"QID12": "How satisfied are you overall?"},
        )

        self.assertEqual(metadata_rows[0]["display_variable_name"], "Overall Score")
        self.assertEqual(metadata_rows[0]["question_label"], "How satisfied are you overall?")

    def test_page_three_editor_preserves_page_two_order(self) -> None:
        metadata_rows = [
            {
                "variable": "campaign_name",
                "display_variable_name": "Campaign Name",
                "question_label": "Campaign Name",
                "detected_type": "Single-Select",
                "answer_choices": "",
                "answer_choices_list": [],
            },
            {
                "variable": "QID10",
                "display_variable_name": "Question 10",
                "question_label": "Question 10 text",
                "detected_type": "Single-Select",
                "answer_choices": "",
                "answer_choices_list": [],
            },
            {
                "variable": "QID2",
                "display_variable_name": "Question 2",
                "question_label": "Question 2 text",
                "detected_type": "Single-Select",
                "answer_choices": "",
                "answer_choices_list": [],
            },
        ]

        editor = prepare_metadata_editor_frame(metadata_rows)

        self.assertEqual(editor["_source_variable"].tolist(), ["campaign_name", "QID10", "QID2"])
        self.assertEqual(editor["variable"].tolist(), ["Campaign Name", "Question 10", "Question 2"])

    def test_metadata_rows_can_be_reordered_from_page_two_columns(self) -> None:
        metadata_rows = [
            {"variable": "QID1", "display_variable_name": "Question 1"},
            {"variable": "QID2", "display_variable_name": "Question 2"},
            {"variable": "QID10", "display_variable_name": "Question 10"},
        ]

        ordered = _order_question_metadata_by_columns(metadata_rows, ["QID10", "QID1"])

        self.assertEqual([row["variable"] for row in ordered], ["QID10", "QID1", "QID2"])


class SnowflakeRespondentCountTest(unittest.TestCase):
    def test_table_denominators_and_counts_use_unique_respondents(self) -> None:
        df = pd.DataFrame(
            {
                RESPONDENT_ID_COLUMN: ["R001", "R001", "R002"],
                "Q1": ["Yes", "Yes", "No"],
            }
        )
        table = _build_question_table(
            df=df,
            question_row={
                "variable": "Q1",
                "display_variable_name": "Question 1",
                "question_label": "Question 1",
                "detected_type": "Single-Select",
                "answer_choices_list": ["Yes", "No"],
            },
            groups=[{"label": "Total", "mask": pd.Series(True, index=df.index)}],
            net_definitions={},
            scale_mappings={},
            alpha=0.05,
            comparison_scope="none",
        )
        total_base = next(section for section in table.sections if section["label"] == "Total Base")
        yes_row = next(row for row in total_base["rows"] if row["label"] == "Yes")

        self.assertEqual(total_base["base_denominators"], [2])
        self.assertEqual(yes_row["counts"], [1])


if __name__ == "__main__":
    unittest.main()

"""Tests for portable project settings snapshots."""

from __future__ import annotations

import unittest

from app.models.project_config import (
    PROJECT_CONFIG_SCHEMA_VERSION,
    PROJECT_SNAPSHOT_KIND,
    build_project_snapshot,
    migrate_project_config,
    unpack_project_payload,
)
from app.state.manager import _order_question_metadata_by_columns
from src.config import build_analysis_variable_catalog


class ProjectConfigSnapshotTests(unittest.TestCase):
    def test_migrate_legacy_config_fills_new_resume_fields(self) -> None:
        migrated = migrate_project_config(
            {
                "variables": {
                    "included_columns": ["Age", "Gender"],
                    "removed_columns": ["IPAddress"],
                },
                "scales": {"AI_Comfort": {"scale_points": ["Low", "High"]}},
            }
        )

        self.assertEqual(migrated["schema_version"], PROJECT_CONFIG_SCHEMA_VERSION)
        self.assertEqual(migrated["variables"]["available_columns"], [])
        self.assertEqual(migrated["variables"]["question_order"], ["Age", "Gender"])
        self.assertEqual(migrated["variables"]["blacklist_removed_columns"], ["IPAddress"])
        self.assertEqual(migrated["data"]["comparison_group_order"], {})
        self.assertEqual(migrated["scales"]["AI_Comfort"]["scale_points"], ["Low", "High"])

    def test_snapshot_round_trips_current_config_payload(self) -> None:
        snapshot = build_project_snapshot(
            {
                "data": {"uploaded_filename": "study.sav"},
                "question_types": {
                    "AI_Attitude": {
                        "display_variable_name": "AI_Attitude",
                        "question_text": "Which best describes your view of AI tools?",
                        "question_type": "Scale / Likert",
                        "answer_choices": ["Unsure", "Open", "Active"],
                    }
                },
                "change_logs": {"scale": ["changed order"]},
            },
            app_version="test",
        )

        self.assertEqual(snapshot["kind"], PROJECT_SNAPSHOT_KIND)
        project_config, info = unpack_project_payload(snapshot)

        self.assertEqual(info["source_filename"], "study.sav")
        self.assertEqual(info["app"]["version"], "test")
        self.assertEqual(project_config["data"]["uploaded_filename"], "study.sav")
        self.assertEqual(
            project_config["question_types"]["AI_Attitude"]["answer_choices"],
            ["Unsure", "Open", "Active"],
        )
        self.assertEqual(project_config["change_logs"]["scale"], ["changed order"])

    def test_unpack_accepts_raw_legacy_config(self) -> None:
        project_config, info = unpack_project_payload(
            {
                "data": {"uploaded_filename": "old.xlsx"},
                "nets": {"Scale": {"Top 2": ["A", "B"]}},
            }
        )

        self.assertEqual(info["kind"], "legacy_project_config")
        self.assertEqual(info["source_filename"], "old.xlsx")
        self.assertEqual(project_config["nets"]["Scale"], {"Top 2": ["A", "B"]})

    def test_restored_metadata_uses_saved_question_order(self) -> None:
        metadata_rows = [
            {"variable": "QID1", "display_variable_name": "Question 1"},
            {"variable": "QID2", "display_variable_name": "Question 2"},
            {"variable": "QID3", "display_variable_name": "Question 3"},
        ]

        ordered = _order_question_metadata_by_columns(metadata_rows, ["QID3", "QID1", "QID2"])

        self.assertEqual([row["variable"] for row in ordered], ["QID3", "QID1", "QID2"])

    def test_analysis_catalog_keeps_comparison_variable_in_question_order(self) -> None:
        metadata_rows = [
            {
                "variable": "QID1",
                "display_variable_name": "Question 1",
                "question_label": "Question 1",
                "detected_type": "Single-Select",
            },
            {
                "variable": "CELL",
                "display_variable_name": "Cell",
                "question_label": "Cell",
                "detected_type": "Ignore",
            },
            {
                "variable": "QID2",
                "display_variable_name": "Question 2",
                "question_label": "Question 2",
                "detected_type": "Single-Select",
            },
        ]

        catalog = build_analysis_variable_catalog(
            metadata_rows,
            custom_variables=[],
            comparison_col="CELL",
            comparison_scheme={"enabled": False},
        )

        self.assertEqual([row["id"] for row in catalog], ["QID1", "CELL", "QID2"])


if __name__ == "__main__":
    unittest.main()

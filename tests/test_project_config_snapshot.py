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


if __name__ == "__main__":
    unittest.main()

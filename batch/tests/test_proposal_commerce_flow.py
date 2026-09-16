"""自社視点の商流調整（提案メール・ルール採点）の単体テスト。"""

from __future__ import annotations

import unittest

from app.constraint_rules import hard_constraint_reject_reason, resolve_proposal_commerce_flow


class ProposalCommerceFlowTests(unittest.TestCase):
    def test_own_company_is_proper(self) -> None:
        self.assertEqual(
            resolve_proposal_commerce_flow(
                own_company_name="株式会社Kanana",
                talent_company_name="株式会社Kanana",
                affiliation="正社員",
                commerce_flow=None,
            ),
            "プロパー",
        )

    def test_other_company_adds_one_hop_with_affiliation(self) -> None:
        self.assertEqual(
            resolve_proposal_commerce_flow(
                own_company_name="株式会社Kanana",
                talent_company_name="A",
                affiliation="正社員",
                commerce_flow=None,
            ),
            "一社先正社員",
        )

    def test_other_company_increments_existing_depth(self) -> None:
        self.assertEqual(
            resolve_proposal_commerce_flow(
                own_company_name="株式会社Kanana",
                talent_company_name="A",
                affiliation="フリーランス",
                commerce_flow="一社先",
            ),
            "二社先フリーランス",
        )

    def test_other_company_freelance_affiliation_only(self) -> None:
        self.assertEqual(
            resolve_proposal_commerce_flow(
                own_company_name="株式会社Kanana",
                talent_company_name="A",
                affiliation="フリーランス",
                commerce_flow=None,
            ),
            "一社先フリーランス",
        )

    def test_unset_own_company_keeps_raw(self) -> None:
        self.assertEqual(
            resolve_proposal_commerce_flow(
                own_company_name="",
                talent_company_name="A",
                affiliation="正社員",
                commerce_flow="一社先",
            ),
            "一社先",
        )

    def test_other_company_does_not_reject_when_project_allows_only_proper(self) -> None:
        adjusted = resolve_proposal_commerce_flow(
            own_company_name="株式会社Kanana",
            talent_company_name="A",
            affiliation="正社員",
            commerce_flow=None,
        )
        self.assertEqual(adjusted, "一社先正社員")
        self.assertIsNone(
            hard_constraint_reject_reason(
                project_foreign_nationality_ng=False,
                talent_is_foreign_national=False,
                project_commerce_flow_limit="エンド直まで",
                talent_commerce_flow=adjusted,
                talent_affiliation="正社員",
            )
        )

    def test_kisha_made_does_not_reject_one_hop(self) -> None:
        adjusted = resolve_proposal_commerce_flow(
            own_company_name="株式会社Kanana",
            talent_company_name="A",
            affiliation="正社員",
            commerce_flow=None,
        )
        self.assertEqual(adjusted, "一社先正社員")
        self.assertIsNone(
            hard_constraint_reject_reason(
                project_foreign_nationality_ng=False,
                talent_is_foreign_national=False,
                project_commerce_flow_limit="貴社まで",
                talent_commerce_flow=adjusted,
                talent_affiliation="正社員",
            )
        )

    def test_issha_saki_allows_one_hop(self) -> None:
        adjusted = resolve_proposal_commerce_flow(
            own_company_name="株式会社Kanana",
            talent_company_name="A",
            affiliation="正社員",
            commerce_flow=None,
        )
        self.assertIsNone(
            hard_constraint_reject_reason(
                project_foreign_nationality_ng=False,
                talent_is_foreign_national=False,
                project_commerce_flow_limit="一社先まで",
                talent_commerce_flow=adjusted,
                talent_affiliation="正社員",
            )
        )

    def test_own_company_passes_kisha_made(self) -> None:
        adjusted = resolve_proposal_commerce_flow(
            own_company_name="株式会社Kanana",
            talent_company_name="株式会社Kanana",
            affiliation="正社員",
            commerce_flow=None,
        )
        self.assertEqual(adjusted, "プロパー")
        self.assertIsNone(
            hard_constraint_reject_reason(
                project_foreign_nationality_ng=False,
                talent_is_foreign_national=False,
                project_commerce_flow_limit="貴社まで",
                talent_commerce_flow=adjusted,
                talent_affiliation="正社員",
            )
        )


if __name__ == "__main__":
    unittest.main()

"""Deterministic tests for Luna/Terra/Sol cognitive routing."""

from __future__ import annotations

import sys
import types
import unittest
from unittest.mock import MagicMock, patch

from core.hybrid_router import TieredRouter, select_model_group


class HybridRouterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.router = TieredRouter.__new__(TieredRouter)
        self.router.local_only_mode = False

    def test_sense_and_watchdog_route_to_luna(self) -> None:
        for phase in ("SENSE", "TEST", "WATCHDOG"):
            with self.subTest(phase=phase):
                self.assertEqual(
                    self.router._get_model_for_phase(phase), TieredRouter.LUNA
                )

    def test_routine_reason_and_act_route_to_terra(self) -> None:
        for phase in ("REASON", "ACT", "TERRA"):
            with self.subTest(phase=phase):
                self.assertEqual(
                    self.router._get_model_for_phase(phase), TieredRouter.TERRA
                )

    def test_novel_and_ambiguous_work_escalates_to_sol(self) -> None:
        for phase in ("NOVEL", "AMBIGUOUS", "BUILDER", "SOL"):
            with self.subTest(phase=phase):
                self.assertEqual(
                    self.router._get_model_for_phase(phase), TieredRouter.SOL
                )

    def test_local_only_mode_overrides_cloud_phase(self) -> None:
        self.router.local_only_mode = True
        self.assertEqual(
            self.router._get_model_for_phase("NOVEL"), "local/deepseek-v4"
        )

    def test_active_model_defaults_to_luna(self) -> None:
        self.assertEqual(select_model_group(0, 0), TieredRouter.LUNA)

    def test_cloud_fallback_order(self) -> None:
        self.assertEqual(TieredRouter._CLOUD_FALLBACKS[TieredRouter.SOL], TieredRouter.TERRA)
        self.assertEqual(TieredRouter._CLOUD_FALLBACKS[TieredRouter.TERRA], TieredRouter.LUNA)
        self.assertNotIn(TieredRouter.LUNA, TieredRouter._CLOUD_FALLBACKS)

    def test_foundry_deployment_configuration(self) -> None:
        deployments = {
            "AZURE_DEPLOYMENT_LUNA": "luna-deployment",
            "AZURE_DEPLOYMENT_TERRA": "terra-deployment",
            "AZURE_DEPLOYMENT_SOL": "sol-deployment",
        }
        fake_litellm = types.ModuleType("litellm")
        fake_litellm.Router = MagicMock()
        with (
            patch.dict("os.environ", deployments, clear=True),
            patch.dict(sys.modules, {"litellm": fake_litellm}),
            patch("core.hybrid_router.os.path.exists", return_value=False),
        ):
            TieredRouter()

        model_list = fake_litellm.Router.call_args.kwargs["model_list"]
        configured = {
            item["model_name"]: item["litellm_params"]["model"]
            for item in model_list
        }
        self.assertEqual(configured[TieredRouter.LUNA], "openai/luna-deployment")
        self.assertEqual(configured[TieredRouter.TERRA], "openai/terra-deployment")
        self.assertEqual(configured[TieredRouter.SOL], "openai/sol-deployment")


if __name__ == "__main__":
    unittest.main()

"""Model Armor: il floor e' letto sia come enforcementEnabled (discovery) sia come enableFloorSettingEnforcement (dati inventati)."""

import unittest

import server


def load_app_namespace() -> dict:
    ns = {"__name__": "janustower_test", "__file__": server.__file__}
    server.load_backend_modules(ns)
    return ns


def matrix_row(ns: dict, floor_setting: dict) -> dict:
    payload = {
        "days": 30,
        "projects": [
            {
                "projectId": "demo-project",
                "name": "Demo Project",
                "vertexRequests": 10,
                "inferenceRequests": 10,
                "modelArmorEnabled": True,
                "modelArmor": {"enabled": True, "templates": [], "floorSetting": floor_setting},
            }
        ],
        "summary": {},
    }
    out = ns["enrich_scan_payload_security"](payload)
    items = out["summary"]["modelArmorMatrix"]["items"]
    return next(i for i in items if i["projectId"] == "demo-project")


class TestModelArmorFloor(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ns = load_app_namespace()

    def test_chiave_della_discovery_attiva_il_floor(self):
        row = matrix_row(self.ns, {"enforcementEnabled": True})
        self.assertTrue(row["floorEnforcement"])
        self.assertEqual(row["coverageStatus"], "PROTECTED")

    def test_chiave_storica_attiva_ancora_il_floor(self):
        row = matrix_row(self.ns, {"enableFloorSettingEnforcement": True})
        self.assertTrue(row["floorEnforcement"])
        self.assertEqual(row["coverageStatus"], "PROTECTED")

    def test_floor_spento_senza_template_non_e_coperto(self):
        row = matrix_row(self.ns, {"enforcementEnabled": False})
        self.assertFalse(row["floorEnforcement"])
        self.assertEqual(row["coverageStatus"], "ENABLED_NO_TEMPLATES")


if __name__ == "__main__":
    unittest.main()

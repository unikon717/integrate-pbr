"""Surface policy contract checks independent of checkpoint inference."""

import copy
import unittest

from integratepbr_engine.usage import load_usage_contract, resolve_surface_usage
from integratepbr_engine.diagnostics import usage_for_selected_row


def surface(value, **extra):
    return {"kind": "render_surface", "value": value, "source": "model JSON",
            "verified": True, "owner": "minecraft:example", "model": "example.json",
            "state": "inventory", "renderer": "vanilla model renderer", "resource": "texture reference", **extra}


class UsageTests(unittest.TestCase):
    def test_verified_surface_overrides_path_and_owner(self):
        evidence = [surface("block_surface"),
                    {"kind": "owner_use", "value": "item", "source": "item model",
                     "verified": False}]
        result = resolve_surface_usage(resource_id="assets/x/textures/item/example.png", evidence=evidence)
        self.assertEqual(result["status"], "block_surface")
        self.assertIn("path_segment:item", result["hints"])

    def test_item_owner_using_complete_block_face(self):
        owner = {"kind": "owner_use", "value": "item", "source": "item model", "verified": False}
        result = resolve_surface_usage(resource_id="assets/x/textures/item/example.png",
                                       evidence=[owner, surface("block_surface")])
        self.assertEqual(result["selected_profile"], "block_surface")

    def test_unknown_renderer_is_incomplete(self):
        for renderer in ("unknown", " UNKNOWN ", "Unknown"):
            record = surface("block_surface", renderer=renderer)
            result = resolve_surface_usage(evidence=[record])
            self.assertEqual(result["status"], "unresolved")
            self.assertIsNone(result["selected_profile"])
            self.assertEqual(result["rule_id"], load_usage_contract()["rules"]["unresolved"])
            self.assertEqual(result["evidence"], [dict(sorted(record.items()))])
            mixed = resolve_surface_usage(evidence=[record, surface("item_surface")])
            self.assertEqual(mixed["status"], "item_surface")
        self.assertEqual(resolve_surface_usage(evidence=[surface("block_surface", renderer="unknown_mod_renderer")])["status"], "block_surface")

    def test_caller_contract_rejects_duplicate_exact_annotation(self):
        contract = copy.deepcopy(load_usage_contract())
        contract["annotations"].append(copy.deepcopy(contract["annotations"][0]))
        with self.assertRaisesRegex(ValueError, "duplicate annotation identity"):
            resolve_surface_usage(contract=contract)

    def test_conflict_and_unresolved(self):
        self.assertEqual(resolve_surface_usage(evidence=[surface("item_surface"), surface("block_surface")])["status"], "conflict")
        self.assertIsNone(resolve_surface_usage(resource_id="assets/x/textures/block/a.png")["selected_profile"])
        incomplete = {"kind": "owner_use", "value": "world", "source": "unknown renderer", "verified": False}
        self.assertEqual(resolve_surface_usage(evidence=[incomplete])["status"], "unresolved")

    def test_order_and_duplicates(self):
        rows = [surface("block_surface"), {"kind": "owner_use", "value": "item", "source": "manifest", "verified": False}]
        self.assertEqual(resolve_surface_usage(evidence=rows), resolve_surface_usage(evidence=rows[::-1] + rows))

    def test_exact_annotations_and_unknown_geometry(self):
        contract = load_usage_contract()
        self.assertEqual(len(contract["annotations"]), 3)
        for row in contract["annotations"]:
            actual = resolve_surface_usage(sample_id=row["sample_id"], reference_entry=row["reference_entry"])
            self.assertEqual(actual["status"], row["render_surface"])
            self.assertEqual(actual["annotation"]["region_geometry"], "unknown")
            self.assertFalse(actual["annotation"]["reviewed_training_label"])
            mismatch = resolve_surface_usage(sample_id=row["sample_id"], reference_entry="other")
            self.assertEqual(mismatch["status"], "unresolved")
            self.assertIsNone(mismatch["guidance"])

    def test_malformed_evidence(self):
        for record in (surface("unknown"), {"kind": "render_surface", "value": "item_surface",
                                                "source": "claim", "verified": True},
                       {"kind": "owner_use", "value": "item", "source": "claim", "verified": "true"}):
            with self.assertRaises(ValueError):
                resolve_surface_usage(evidence=[record])

    def test_diagnostic_fixture(self):
        row = {"sample_id": "other", "reference_entry": "assets/x/textures/block/test.png",
               "source": "textures/block/test.png"}
        self.assertEqual(usage_for_selected_row(row, load_usage_contract())["status"], "unresolved")


if __name__ == "__main__":
    unittest.main()

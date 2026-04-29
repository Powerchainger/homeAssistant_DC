"""Unit tests for ``TrailingPerSecondEmitter`` (no Home Assistant runtime)."""

from __future__ import annotations

import importlib.util
import sys
import types
import unittest
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
_PC_PATH = _REPO_ROOT / "custom_components" / "powerchainger"


def _ensure_powerchainger_pkg_loaded() -> None:
    if "custom_components.powerchainger.trailing_emitter" in sys.modules:
        return
    cc_path = _REPO_ROOT / "custom_components"
    if "custom_components" not in sys.modules:
        m = types.ModuleType("custom_components")
        m.__path__ = [str(cc_path)]
        sys.modules["custom_components"] = m
    if "custom_components.powerchainger" not in sys.modules:
        m = types.ModuleType("custom_components.powerchainger")
        m.__path__ = [str(_PC_PATH)]
        sys.modules["custom_components.powerchainger"] = m

    def _load_file(modname: str, filename: str) -> None:
        path = _PC_PATH / filename
        spec = importlib.util.spec_from_file_location(modname, path)
        assert spec and spec.loader
        mod = importlib.util.module_from_spec(spec)
        sys.modules[modname] = mod
        spec.loader.exec_module(mod)

    _load_file("custom_components.powerchainger.models", "models.py")
    _load_file("custom_components.powerchainger.trailing_emitter", "trailing_emitter.py")


_ensure_powerchainger_pkg_loaded()

from custom_components.powerchainger.models import Measurement  # noqa: E402
from custom_components.powerchainger.trailing_emitter import (  # noqa: E402
    NS_PER_SECOND,
    EntityEmitMeta,
    TrailingPerSecondEmitter,
)

META = EntityEmitMeta(
    user_id="u1",
    entity_id="sensor.a",
    entity_name="A",
    serial="A",
    device_id="d1",
)


def _by_second(rows: list[Measurement]) -> dict[int, float]:
    return {m.timestamp // NS_PER_SECOND: m.wattage for m in rows}


class TrailingEmitterTest(unittest.TestCase):
    def test_lag10_emits_when_sample_second_matures(self) -> None:
        em = TrailingPerSecondEmitter(lag_seconds=10, max_catchup_seconds=120)
        em.set_entities({"sensor.a": META})
        self.assertEqual(em.flush(now_sec=20), [])
        em.note_sample(META, sample_unix_second=15, wattage=12.0)
        self.assertEqual(_by_second(em.flush(now_sec=25)), {10: 0.0, 11: 0.0, 12: 0.0, 13: 0.0, 14: 0.0})
        out = em.flush(now_sec=26)
        self.assertEqual(_by_second(out), {15: 12.0})

    def test_same_second_last_value_wins(self) -> None:
        em = TrailingPerSecondEmitter(lag_seconds=2, max_catchup_seconds=60)
        em.set_entities({"sensor.a": META})
        em.flush(now_sec=3)
        em.note_sample(META, 1, 10.0)
        em.note_sample(META, 1, 22.0)
        out = em.flush(now_sec=4)
        self.assertEqual(_by_second(out), {1: 22.0})

    def test_gap_filled_with_zero(self) -> None:
        em = TrailingPerSecondEmitter(lag_seconds=2, max_catchup_seconds=60)
        em.set_entities({"sensor.a": META})
        em.flush(now_sec=3)
        em.note_sample(META, 1, 5.0)
        out = em.flush(now_sec=5)
        self.assertEqual(_by_second(out), {1: 5.0, 2: 0.0})

    def test_timestamps_are_start_of_second_ns(self) -> None:
        em = TrailingPerSecondEmitter(lag_seconds=2, max_catchup_seconds=60)
        em.set_entities({"sensor.a": META})
        em.flush(now_sec=3)
        em.note_sample(META, 7, 3.0)
        rows = em.flush(now_sec=10)
        row = next(m for m in rows if m.timestamp // NS_PER_SECOND == 7)
        self.assertEqual(row.timestamp, 7 * NS_PER_SECOND)
        self.assertEqual(row.wattage, 3.0)

    def test_idle_to_active_no_extra_same_second_zero(self) -> None:
        em = TrailingPerSecondEmitter(lag_seconds=2, max_catchup_seconds=60)
        em.set_entities({"sensor.a": META})
        em.flush(now_sec=3)
        em.note_sample(META, 4, 0.0)
        em.note_sample(META, 5, 150.0)
        out = em.flush(now_sec=8)
        self.assertEqual(_by_second(out)[4], 0.0)
        self.assertEqual(_by_second(out)[5], 150.0)

    def test_catchup_caps_span(self) -> None:
        em = TrailingPerSecondEmitter(lag_seconds=1, max_catchup_seconds=3)
        em.set_entities({"sensor.a": META})
        em.flush(now_sec=3)
        em.note_sample(META, 9, 99.0)
        out = em.flush(now_sec=12)
        seconds = sorted(_by_second(out))
        self.assertEqual(seconds, [8, 9, 10])
        self.assertEqual(_by_second(out)[9], 99.0)
        self.assertEqual(_by_second(out)[8], 0.0)

    def test_late_sample_after_warmup_is_skipped(self) -> None:
        em = TrailingPerSecondEmitter(lag_seconds=2, max_catchup_seconds=60)
        em.set_entities({"sensor.a": META})
        em.flush(now_sec=3)
        em.note_sample(META, 0, 999.0)
        out = em.flush(now_sec=10)
        self.assertNotIn(0, _by_second(out))

    def test_multi_entity_same_timestamp_order(self) -> None:
        meta_b = EntityEmitMeta(
            user_id="u1",
            entity_id="sensor.b",
            entity_name="B",
            serial="B",
            device_id=None,
        )
        em = TrailingPerSecondEmitter(lag_seconds=2, max_catchup_seconds=60)
        em.set_entities({"sensor.a": META, "sensor.b": meta_b})
        em.flush(now_sec=3)
        em.note_sample(META, 1, 1.0)
        em.note_sample(meta_b, 1, 2.0)
        out = em.flush(now_sec=4)
        self.assertEqual(len(out), 2)
        self.assertEqual(out[0].entity_id, "sensor.a")
        self.assertEqual(out[1].entity_id, "sensor.b")


if __name__ == "__main__":
    unittest.main()

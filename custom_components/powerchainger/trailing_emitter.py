"""Trailing per-second emission: bucket HA samples, fill gaps with 0, fixed lag.

This is separate from transport buffering in ``socketio_client.PowerChaingerSocketClient``,
which only queues measurements when the Socket.IO connection is down.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import logging
import time
from typing import Callable

from .models import Measurement

_LOGGER = logging.getLogger(__name__)


NS_PER_SECOND = 1_000_000_000


@dataclass
class EntityEmitMeta:
    """Static fields copied into each emitted ``Measurement``."""

    user_id: str
    entity_id: str
    entity_name: str
    serial: str
    device_id: str | None


@dataclass
class _EntityStreamState:
    meta: EntityEmitMeta
    last_emitted_second: int | None = None
    pending_watt_by_second: dict[int, float] = field(default_factory=dict)


class TrailingPerSecondEmitter:
    """One row per entity per calendar second, delayed by ``lag_seconds``."""

    def __init__(
        self,
        lag_seconds: int,
        max_catchup_seconds: int,
        now_fn: Callable[[], float] | None = None,
    ) -> None:
        if lag_seconds < 0:
            raise ValueError("lag_seconds must be non-negative")
        if max_catchup_seconds < 1:
            raise ValueError("max_catchup_seconds must be at least 1")
        self._lag = lag_seconds
        self._max_catchup = max_catchup_seconds
        self._now_fn = now_fn or time.time
        self._streams: dict[str, _EntityStreamState] = {}

    def set_entities(self, metas: dict[str, EntityEmitMeta]) -> None:
        """Replace tracked entities; new keys start fresh; removed keys are dropped."""
        next_streams: dict[str, _EntityStreamState] = {}
        for entity_id, meta in metas.items():
            prev = self._streams.get(entity_id)
            if prev is not None:
                next_streams[entity_id] = prev
                prev.meta = meta
            else:
                next_streams[entity_id] = _EntityStreamState(meta=meta)
        self._streams = next_streams

    def note_sample(self, meta: EntityEmitMeta, sample_unix_second: int, wattage: float) -> None:
        """Record a HA reading for ``sample_unix_second`` (last value wins for that second)."""
        st = self._streams.get(meta.entity_id)
        if st is None:
            st = _EntityStreamState(meta=meta)
            self._streams[meta.entity_id] = st
        else:
            st.meta = meta
        if st.last_emitted_second is not None and sample_unix_second <= st.last_emitted_second:
            _LOGGER.debug(
                "Skipping sample for %s at second %s (stream already emitted through %s)",
                meta.entity_id,
                sample_unix_second,
                st.last_emitted_second,
            )
            return
        st.pending_watt_by_second[sample_unix_second] = wattage

    def flush(self, now_sec: int | None = None) -> list[Measurement]:
        """Emit all ready seconds for every tracked entity (gap-filled with 0)."""
        if now_sec is None:
            now_sec = int(self._now_fn())
        emit_through = now_sec - self._lag - 1
        if emit_through < 0:
            return []

        out: list[Measurement] = []
        for entity_id, st in self._streams.items():
            if st.last_emitted_second is None:
                st.last_emitted_second = emit_through
                continue

            start = st.last_emitted_second + 1
            if start > emit_through:
                continue

            span = emit_through - start + 1
            if span > self._max_catchup:
                start = emit_through - self._max_catchup + 1
                st.pending_watt_by_second = {
                    sec: w for sec, w in st.pending_watt_by_second.items() if sec >= start
                }

            for sec in range(start, emit_through + 1):
                watt = float(st.pending_watt_by_second.pop(sec, 0.0))
                ts = sec * NS_PER_SECOND
                out.append(
                    Measurement(
                        user_id=st.meta.user_id,
                        timestamp=ts,
                        serial=st.meta.serial,
                        wattage=watt,
                        entity_id=st.meta.entity_id,
                        entity_name=st.meta.entity_name,
                        device_id=st.meta.device_id,
                    )
                )
            st.last_emitted_second = emit_through

        out.sort(key=lambda m: (m.timestamp, m.entity_id))
        return out

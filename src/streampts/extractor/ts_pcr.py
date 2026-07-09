from __future__ import annotations

from pathlib import Path

from streampts.models import PcrPoint

TS_PACKET_SIZE = 188


def extract_pcr_by_pid(input_path: Path) -> dict[int, list[PcrPoint]]:
    """Extract PCR from MPEG-TS transport packets when ffprobe omits pcr_time."""
    by_pid: dict[int, list[PcrPoint]] = {}
    with input_path.open("rb") as handle:
        packet_index = 0
        while True:
            raw = handle.read(TS_PACKET_SIZE)
            if len(raw) < TS_PACKET_SIZE:
                break
            if raw[0] != 0x47:
                packet_index += 1
                continue

            pid = ((raw[1] & 0x1F) << 8) | raw[2]
            adaptation = (raw[3] >> 4) & 0x3
            packet_index += 1

            if adaptation not in (2, 3):
                continue

            adaptation_length = raw[4]
            if adaptation_length == 0:
                continue

            flags = raw[5]
            if not (flags & 0x10):
                continue

            pcr_base = (
                (raw[6] << 25)
                | (raw[7] << 17)
                | (raw[8] << 9)
                | (raw[9] << 1)
                | (raw[10] >> 7)
            )
            pcr_ext = ((raw[10] & 0x01) << 8) | raw[11]
            pcr = pcr_base * 300 + pcr_ext
            pcr_time = pcr / 27_000_000.0
            by_pid.setdefault(pid, []).append(
                PcrPoint(packet_index=packet_index, pcr=pcr, pcr_time=pcr_time)
            )

    return by_pid

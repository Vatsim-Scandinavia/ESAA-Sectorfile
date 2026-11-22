"""Put lake fills above land in ESAA RTC1/RTC2 (SCT + GNG paste files)."""

from __future__ import annotations

from pathlib import Path
import re

SCT_PATH = Path(
    r"C:\Users\maxlk\AppData\Roaming\EuroScope\ESAA-Sweden_20261109173548-261101-0002.sct"
)
TOOLS = Path(__file__).resolve().parent

coord_re = re.compile(
    r"([NS])(\d{3})\.(\d{2})\.(\d{2})\.(\d{3})\s+([EW])(\d{3})\.(\d{2})\.(\d{2})\.(\d{3})"
)


def parse_all_rtc(text: list[str]) -> list[tuple[str, list[str]]]:
    polys: list[tuple[str, list[str]]] = []
    i = 0
    while i < len(text):
        if text[i].startswith("REGIONNAME ESAA RTC"):
            i += 1
            parts = text[i].split(None, 1)
            color = parts[0]
            coords: list[str] = []
            if len(parts) > 1:
                m = coord_re.search(parts[1])
                if m:
                    coords.append(m.group(0))
            i += 1
            while i < len(text) and not text[i].startswith("REGIONNAME ") and not (
                text[i].startswith("[") and text[i].strip().endswith("]")
            ):
                m = coord_re.search(text[i])
                if m:
                    coords.append(m.group(0))
                i += 1
            polys.append((color, coords))
            continue
        i += 1
    return polys


def find_rtc_span(text: list[str]) -> tuple[int, int]:
    start = None
    end = len(text)
    for i, line in enumerate(text):
        if line.startswith("REGIONNAME ESAA RTC"):
            if start is None:
                start = i
        elif start is not None:
            if line.startswith("REGIONNAME ") and not line.startswith("REGIONNAME ESAA RTC"):
                end = i
                break
            if line.startswith("[") and line.strip().endswith("]"):
                end = i
                break
    if start is None:
        raise RuntimeError("ESAA RTC regions not found")
    return start, end


def emit_gng(polys: list[tuple[str, list[str]]]) -> str:
    lines: list[str] = []
    for color, coords in polys:
        lines.append(color)
        lines.append(coords[0])
        for c in coords[1:]:
            lines.append(f"                           {c}")
    return "\n".join(lines) + "\n"


def nbytes(polys: list[tuple[str, list[str]]]) -> int:
    return len(emit_gng(polys).encode("utf-8"))


def emit_sct(name: str, color: str, coords: list[str]) -> list[str]:
    lines = [f"REGIONNAME {name}"]
    lines.append(f"{color}            {coords[0]}")
    for c in coords[1:]:
        lines.append(f"                           {c}")
    return lines


def main() -> None:
    raw = SCT_PATH.read_bytes()
    text = raw.decode("latin-1", errors="replace").splitlines()
    polys = parse_all_rtc(text)

    water: list[tuple[str, list[str]]] = []
    lakes: list[tuple[str, list[str]]] = []
    land: list[tuple[str, list[str]]] = []
    for color, coords in polys:
        if color == "COLOR_Terrain2":
            land.append((color, coords))
        elif color == "COLOR_Terrain7":
            (lakes if len(coords) >= 10 else water).append((color, coords))

    print(f"classified water={len(water)} land={len(land)} lakes={len(lakes)}")

    # RTC1 = water + land until ~half; RTC2 = remaining land + lakes last
    half = nbytes(water + land + lakes) // 2
    rtc1 = list(water)
    for poly in land:
        if nbytes(rtc1) < half:
            rtc1.append(poly)
        else:
            break
    n1 = len(rtc1) - len(water)
    rtc2 = land[n1:] + lakes

    (TOOLS / "ESAA_RTC1_GNG.txt").write_text(emit_gng(rtc1), encoding="utf-8")
    (TOOLS / "ESAA_RTC2_GNG.txt").write_text(emit_gng(rtc2), encoding="utf-8")
    (TOOLS / "ESAA_RTC_GNG.txt").write_text(emit_gng(water + land + lakes), encoding="utf-8")
    print(
        f"GNG RTC1 polys={len(rtc1)} bytes={(TOOLS / 'ESAA_RTC1_GNG.txt').stat().st_size}"
    )
    print(
        f"GNG RTC2 polys={len(rtc2)} lakes_at_end={len(lakes)} "
        f"bytes={(TOOLS / 'ESAA_RTC2_GNG.txt').stat().st_size}"
    )

    start, end = find_rtc_span(text)
    out: list[str] = []
    for color, coords in rtc1:
        out.extend(emit_sct("ESAA RTC1", color, coords))
    for color, coords in rtc2:
        out.extend(emit_sct("ESAA RTC2", color, coords))

    new_text = text[:start] + out + text[end:]
    nl = b"\r\n" if b"\r\n" in raw else b"\n"
    payload = nl.join(line.encode("latin-1", errors="replace") for line in new_text)
    if raw.endswith(b"\n") or raw.endswith(b"\r\n"):
        payload += nl
    SCT_PATH.write_bytes(payload)
    print(f"Updated SCT RTC span [{start + 1}..{end}] -> {len(out)} lines")


if __name__ == "__main__":
    main()

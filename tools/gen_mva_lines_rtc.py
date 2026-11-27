"""Build combined GRP MAP:AMA/MVA (lines + labels) from TopSky AMA/MVA.

- All MVA LINE/TEXT in white (no CTR/TMA border filter)
- AMA grid LINE + TEXT in AMA color
- Obstacle circle rings kept as lines (like TopSky)
- Removes MAP:MVA, MAP:MVA LINES, MAP:OBSTACLE CIRCLES
"""

from __future__ import annotations

import math
import re
from pathlib import Path

ESAA = Path(__file__).resolve().parents[1]
MAPS = ESAA / "Plugins" / "GRpluginMaps.txt"
TOPSKY = ESAA / "OTHER" / "TopSkyMaps.txt"
EUROSCOPE = Path.home() / "AppData" / "Roaming" / "EuroScope"

TOL_NM = 0.02
EARTH_NM = 3440.065

MAP_NAME = "MAP:AMA/MVA:T"
REMOVE_MAPS = (
    "MAP:MVA LINES:T",
    "MAP:OBSTACLE CIRCLES:T",
    "MAP:MVA:T",
    "MAP:AMA/MVA:T",
)

COLORDEFS = (
    ("COLORDEF:AMA:", "COLORDEF:AMA:150:190:200\n"),
    ("COLORDEF:AMATEXT:", "COLORDEF:AMATEXT:75:110:120\n"),
)


def parse_dms(tok: str) -> float:
    hemi = tok[0]
    deg, mn, sec, frc = tok[1:].split(".")
    val = int(deg) + int(mn) / 60.0 + (int(sec) + int(frc) / 1000.0) / 3600.0
    return -val if hemi in "SW" else val


def dist_nm(a: tuple[float, float], b: tuple[float, float]) -> float:
    lat1, lon1 = map(math.radians, a)
    lat2, lon2 = map(math.radians, b)
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    h = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return 2 * EARTH_NM * math.asin(min(1.0, math.sqrt(h)))


def find_sct() -> Path:
    cands = list(EUROSCOPE.glob("ESAA-Sweden*.sct")) + list(ESAA.glob("ESAA-Sweden*.sct"))
    if not cands:
        raise FileNotFoundError("No ESAA-Sweden*.sct found")
    return max(cands, key=lambda p: p.stat().st_mtime)


def quantize(pt: tuple[float, float]) -> tuple[int, int]:
    cell = TOL_NM / 60.0
    return (int(round(pt[0] / cell)), int(round(pt[1] / cell)))


def parse_sct_segments(sct_text: str) -> list[tuple[tuple[float, float], tuple[float, float]]]:
    segs: list[tuple[tuple[float, float], tuple[float, float]]] = []
    coord_re = re.compile(
        r"(N\d{3}\.\d{2}\.\d{2}\.\d{3})\s+([EW]\d{3}\.\d{2}\.\d{2}\.\d{3})"
    )

    def add_from_block(block: str, name_prefixes: list[str] | None = None) -> None:
        for l in block.splitlines():
            if name_prefixes is not None:
                name = l[:40].strip() if l[:1].isalnum() else ""
                if name and not any(name.startswith(p) for p in name_prefixes):
                    continue
            pts = coord_re.findall(l)
            if len(pts) >= 2:
                a = (parse_dms(pts[0][0]), parse_dms(pts[0][1]))
                b = (parse_dms(pts[1][0]), parse_dms(pts[1][1]))
                segs.append((a, b))

    for sect in ("ARTCC HIGH", "ARTCC LOW", "ARTCC"):
        m = re.search(rf"\[{re.escape(sect)}\](.*?)(\n\[|\Z)", sct_text, re.S | re.I)
        if m:
            add_from_block(m.group(1))

    m = re.search(r"\[GEO\](.*?)(\n\[|\Z)", sct_text, re.S | re.I)
    if m:
        add_from_block(m.group(1), ["ESNJ TMA", "ESNJ CTR", "ESMV TMA", "ESMV CTR"])
    return segs


def border_keys(
    borders: list[tuple[tuple[float, float], tuple[float, float]]],
) -> set[tuple[tuple[int, int], tuple[int, int]]]:
    keys: set[tuple[tuple[int, int], tuple[int, int]]] = set()
    for c, d in borders:
        keys.add(tuple(sorted((quantize(c), quantize(d)))))  # type: ignore[arg-type]
    return keys


def coincides(
    mva: tuple[tuple[float, float], tuple[float, float]],
    keys: set[tuple[tuple[int, int], tuple[int, int]]],
) -> bool:
    a, b = mva
    return tuple(sorted((quantize(a), quantize(b)))) in keys  # type: ignore[arg-type]


def convert_label(lab: str) -> str:
    lab = lab.strip()
    m = re.fullmatch(r"(\d+)", lab)
    if m:
        return f"{int(m.group(1)) / 10:.1f}"
    m = re.fullmatch(r"([A-Za-z]+)\s+(\d+)", lab)
    if m:
        return f"{m.group(1)} {int(m.group(2)) / 10:.1f}"
    m = re.search(r"(\d+)\s*$", lab)
    if m:
        return lab[: m.start()] + f"{int(m.group(1)) / 10:.1f}"
    return lab


def _parse_items(
    block_lines: list[str],
) -> tuple[list[tuple[str, str, str, str]], list[tuple[str, str, str]]]:
    segs: list[tuple[str, str, str, str]] = []
    texts: list[tuple[str, str, str]] = []
    for l in block_lines:
        if l.startswith("LINE:"):
            p = l.split(":")
            if len(p) >= 5:
                segs.append((p[1], p[2], p[3], p[4]))
        elif l.startswith("TEXT:"):
            p = l.split(":")
            if len(p) >= 5 and p[1] == "":
                texts.append((p[2], p[3], convert_label(":".join(p[4:]))))
            elif len(p) >= 4:
                texts.append((p[1], p[2], convert_label(":".join(p[3:]))))
    return segs, texts


def parse_topsky_ama_mva(
    text: str,
) -> tuple[
    list[tuple[str, str, str, str]],
    list[tuple[str, str, str]],
    list[tuple[str, str, str, str]],
    list[tuple[str, str, str]],
]:
    """Return (mva_lines, mva_texts, ama_lines, ama_texts) from TopSky MAP:AMA/MVA."""
    lines = text.splitlines()
    start = next(i for i, l in enumerate(lines) if l.startswith("MAP:AMA/MVA"))
    end = next(i for i in range(start + 1, len(lines)) if lines[i].startswith("MAP:"))
    block = lines[start:end]
    ama_idx = next(
        (i for i, l in enumerate(block) if "AMA - Area Minimum Altitude" in l),
        len(block),
    )
    mva_lines, mva_texts = _parse_items(block[:ama_idx])
    ama_lines, ama_texts = _parse_items(block[ama_idx:])
    return mva_lines, mva_texts, ama_lines, ama_texts


def remove_map(maps_text: str, map_name: str) -> str:
    if map_name not in maps_text:
        return maps_text
    start = maps_text.find(map_name)
    probe = start
    block_start = start
    while True:
        prev_nl = maps_text.rfind("\n", 0, probe)
        if prev_nl < 0:
            break
        prev_line = maps_text[prev_nl + 1 : probe]
        if prev_line.strip() == "" or prev_line.lstrip().startswith("//"):
            block_start = prev_nl + 1
            probe = prev_nl
            continue
        break
    rest = maps_text.find("\nMAP:", start + 1)
    if rest < 0:
        rest = len(maps_text)
    return maps_text[:block_start] + maps_text[rest:].lstrip("\n")


def ensure_colordefs(maps_text: str) -> str:
    for needle, line in COLORDEFS:
        if needle in maps_text:
            continue
        # insert after COLORDEF:MVA:
        mva = maps_text.find("COLORDEF:MVA:")
        if mva < 0:
            maps_text = line + maps_text
            continue
        nl = maps_text.find("\n", mva)
        maps_text = maps_text[: nl + 1] + line + maps_text[nl + 1 :]
    return maps_text


def filter_lines(
    raw: list[tuple[str, str, str, str]],
    keys: set[tuple[tuple[int, int], tuple[int, int]]],
) -> tuple[list[tuple[str, str, str, str]], int]:
    kept: list[tuple[str, str, str, str]] = []
    dropped = 0
    for lat1, lon1, lat2, lon2 in raw:
        a = (parse_dms(lat1), parse_dms(lon1))
        b = (parse_dms(lat2), parse_dms(lon2))
        if coincides((a, b), keys):
            dropped += 1
        else:
            kept.append((lat1, lon1, lat2, lon2))
    return kept, dropped


def build_map(
    mva_kept: list[tuple[str, str, str, str]],
    mva_texts: list[tuple[str, str, str]],
    ama_kept: list[tuple[str, str, str, str]],
    ama_texts: list[tuple[str, str, str]],
) -> str:
    rows = [
        MAP_NAME,
        "AIRPORT:ESAA",
        "FOLDER:MVA/OBST",
        "ASRDATA:MVA,RTC",
        "ACTIVE:0",
        "FONTSIZE:=:15",
        "// Combined AMA/MVA from TopSky (all MVA lines; AMA line+text same color)",
        "// --- MVA ---",
        "COLOR:WHITE",
        "STYLE:SOLID:1",
    ]
    for lat1, lon1, lat2, lon2 in mva_kept:
        rows.append(f"LINE:{lat1}:{lon1}:{lat2}:{lon2}")
    rows.append("COLOR:WHITE")
    for lat, lon, lab in mva_texts:
        rows.append(f"TEXT:{lat}:{lon}:{lab}")
    rows.append("// --- AMA (dashed) ---")
    rows.append("COLOR:AMA")
    rows.append("STYLE:DASH:1")
    for lat1, lon1, lat2, lon2 in ama_kept:
        rows.append(f"LINE:{lat1}:{lon1}:{lat2}:{lon2}")
    rows.append("COLOR:AMA")
    for lat, lon, lab in ama_texts:
        rows.append(f"TEXT:{lat}:{lon}:{lab}")
    return "\n".join(rows) + "\n\n"


def main() -> None:
    topsky = TOPSKY.read_bytes().decode("cp1252")
    mva_raw, mva_texts, ama_raw, ama_texts = parse_topsky_ama_mva(topsky)
    maps = MAPS.read_bytes().decode("cp1252")
    sct_path = find_sct()
    borders = parse_sct_segments(sct_path.read_text(encoding="cp1252", errors="replace"))
    keys = border_keys(borders)

    # Keep all MVA lines (including those that coincide with CTR/TMA borders)
    mva_kept = list(mva_raw)
    mva_dropped = 0
    ama_kept, ama_dropped = filter_lines(ama_raw, keys)

    maps = ensure_colordefs(maps)
    for name in REMOVE_MAPS:
        maps = remove_map(maps, name)

    block = build_map(mva_kept, mva_texts, ama_kept, ama_texts)
    anchor = maps.find("MAP:MVA 2000 FT:T")
    if anchor < 0:
        anchor = maps.find("MAP:AIRPORTS:T")
    if anchor < 0:
        obst = maps.find("MAP:OBSTACLES:T")
        if obst >= 0:
            nxt = maps.find("\nMAP:", obst + 1)
            anchor = nxt + 1 if nxt >= 0 else len(maps)
        else:
            raise SystemExit("no insert anchor found")
    maps = maps[:anchor] + block + maps[anchor:]

    MAPS.write_bytes(maps.encode("cp1252"))
    print(f"SCT: {sct_path.name}")
    print(f"CTR/TMA border segments: {len(borders)} ({len(keys)} unique keys)")
    print(
        f"MVA: kept {len(mva_kept)}/{len(mva_raw)} lines "
        f"(dropped border={mva_dropped}), texts={len(mva_texts)}"
    )
    print(
        f"AMA: kept {len(ama_kept)}/{len(ama_raw)} lines "
        f"(dropped border={ama_dropped}), texts={len(ama_texts)}"
    )
    print(f"Updated {MAPS}")


if __name__ == "__main__":
    main()

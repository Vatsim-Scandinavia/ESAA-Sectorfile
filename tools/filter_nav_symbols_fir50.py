"""
Deactivate NAV symbols outside ESAA FIR + 50 NM.

- GRpluginMaps.txt: comment out SYMBOL / SYMBOL/LB lines under
  AIRPORTS, VOR, NDB, FIXES, RNP, MIL, VRP (+ L / MIL variants)
- ASR/*.asr: drop Airports:/VORs:/NDBs:/Fixes: rows outside the clip
"""

from __future__ import annotations

import math
import re
from pathlib import Path

from shapely.geometry import Point, Polygon
from shapely.ops import transform

ROOT = Path(__file__).resolve().parents[1]
TOPSKY_PATH = ROOT / "OTHER" / "TopSkyAreas.txt"
GRP_PATH = ROOT / "Plugins" / "GRpluginMaps.txt"
ASR_DIR = ROOT / "ASR"
EUROSCOPE = Path.home() / "AppData" / "Roaming" / "EuroScope"

FIR_BUFFER_NM = 50.0
FIR_SIMPLIFY_NM = 8.0

# Base map titles (MAP:<title>:…) that should be FIR-clipped
NAV_MAP_PREFIXES = (
    "AIRPORTS",
    "VOR",
    "NDB",
    "FIXES",
    "RNP",
    "MIL",
    "VRP",
)

ASR_PREFIXES = ("Airports:", "VORs:", "NDBs:", "Fixes:")

tops_coord_re = re.compile(
    r"([NS])(\d{3})\.(\d{2})\.(\d{2})\.(\d{3}):([EW])(\d{3})\.(\d{2})\.(\d{2})\.(\d{3})"
)
coord_re = re.compile(
    r"([NS])(\d{3})\.(\d{2})\.(\d{2})\.(\d{3})\s+([EW])(\d{3})\.(\d{2})\.(\d{2})\.(\d{3})"
)
sym_re = re.compile(r"^(//)?\s*SYMBOL(?:/LB)?:([^:]+):(.+)$")
coord_sym_re = re.compile(
    r"^([NS]\d{3}\.\d{2}\.\d{2}\.\d{3}):([EW]\d{3}\.\d{2}\.\d{2}\.\d{3})(?::.*)?$"
)
lat_re = re.compile(r"^([NS])(\d{3})\.(\d{2})\.(\d{2})\.(\d{3})$")
lon_re = re.compile(r"^([EW])(\d{3})\.(\d{2})\.(\d{2})\.(\d{3})$")


def dms_to_deg(hemi: str, d: int, mi: int, s: int, f: int) -> float:
    val = d + mi / 60 + (s + f / 1000) / 3600
    return -val if hemi in ("S", "W") else val


def find_sct() -> Path:
    cands = list(EUROSCOPE.glob("ESAA-Sweden*.sct")) + list(ROOT.glob("ESAA-Sweden*.sct"))
    if not cands:
        raise FileNotFoundError("No ESAA-Sweden*.sct found")
    return max(cands, key=lambda p: p.stat().st_mtime)


def parse_esa_fir_polygon(path: Path) -> Polygon:
    coords: list[tuple[float, float]] = []
    in_area = False
    for line in path.read_text(encoding="latin-1", errors="replace").splitlines():
        s = line.strip()
        if s.startswith("AREA:"):
            if in_area:
                break
            if s == "AREA:TCTA:ESAA FIR":
                in_area = True
            continue
        if not in_area:
            continue
        if not s or s.startswith("//") or s.startswith("LIMITS:") or s.startswith("TCTA_"):
            continue
        m = tops_coord_re.fullmatch(s)
        if not m:
            continue
        lat = dms_to_deg(m.group(1), int(m.group(2)), int(m.group(3)), int(m.group(4)), int(m.group(5)))
        lon = dms_to_deg(m.group(6), int(m.group(7)), int(m.group(8)), int(m.group(9)), int(m.group(10)))
        coords.append((lon, lat))
    if len(coords) < 3:
        raise RuntimeError(f"ESAA FIR not found in {path}")
    if coords[0] != coords[-1]:
        coords.append(coords[0])
    poly = Polygon(coords)
    if not poly.is_valid:
        poly = poly.buffer(0)
    if poly.geom_type == "Polygon":
        return poly
    return max(poly.geoms, key=lambda p: p.area)


def buffer_polygon_nm(poly: Polygon, nm: float, simplify_nm: float) -> Polygon:
    lat0 = poly.centroid.y
    cos_lat = max(0.2, math.cos(math.radians(lat0)))

    def to_nm(x, y, z=None):
        return (x * 60.0 * cos_lat, y * 60.0)

    def to_ll(x, y, z=None):
        return (x / (60.0 * cos_lat), y / 60.0)

    xy = transform(to_nm, poly)
    buf = xy.buffer(nm)
    if simplify_nm > 0:
        buf = buf.simplify(simplify_nm, preserve_topology=True)
    out = transform(to_ll, buf)
    if out.geom_type == "Polygon":
        return out
    return max(out.geoms, key=lambda p: p.area)


def parse_coord_match(m: re.Match) -> tuple[float, float]:
    lat = dms_to_deg(m.group(1), int(m.group(2)), int(m.group(3)), int(m.group(4)), int(m.group(5)))
    lon = dms_to_deg(m.group(6), int(m.group(7)), int(m.group(8)), int(m.group(9)), int(m.group(10)))
    return lon, lat


def parse_lat_lon_tokens(lat_s: str, lon_s: str) -> tuple[float, float]:
    ma = lat_re.fullmatch(lat_s)
    mb = lon_re.fullmatch(lon_s)
    if not ma or not mb:
        raise ValueError(f"bad lat/lon {lat_s} {lon_s}")
    lat = dms_to_deg(ma.group(1), int(ma.group(2)), int(ma.group(3)), int(ma.group(4)), int(ma.group(5)))
    lon = dms_to_deg(mb.group(1), int(mb.group(2)), int(mb.group(3)), int(mb.group(4)), int(mb.group(5)))
    return lon, lat


def load_sct_lookups(sct_path: Path) -> dict[str, tuple[float, float]]:
    text = sct_path.read_bytes().decode("latin-1", errors="replace").splitlines()

    def section(name: str) -> list[str]:
        start = None
        for i, line in enumerate(text):
            if line.strip() == name:
                start = i + 1
                continue
            if start is not None and line.startswith("[") and line.strip().endswith("]"):
                return text[start:i]
        return text[start:] if start is not None else []

    lookups: dict[str, tuple[float, float]] = {}
    for sec in ("[VOR]", "[NDB]", "[FIXES]", "[AIRPORT]"):
        for line in section(sec):
            if not line.strip() or line.startswith(";"):
                continue
            m = coord_re.search(line)
            if not m:
                continue
            name = line[: m.start()].strip().split()[0]
            lookups[name] = parse_coord_match(m)
    return lookups


def inside_clip(clip: Polygon, lon: float, lat: float) -> bool:
    p = Point(lon, lat)
    return clip.contains(p) or clip.touches(p)


def is_nav_map(title: str) -> bool:
    """True for NAV symbol maps; skip ground maps like 'MIL Aprons'."""
    t = title.strip()
    if t.startswith("MIL ") and not t.startswith("MIL +"):
        return False  # MIL Aprons etc.
    for prefix in NAV_MAP_PREFIXES:
        if t == prefix or t.startswith(prefix + " ") or t.startswith(prefix + "+"):
            return True
    return False


def filter_grplugin(clip: Polygon, lookups: dict[str, tuple[float, float]]) -> None:
    raw = GRP_PATH.read_bytes().decode("cp1252")
    lines = raw.splitlines()
    out: list[str] = []
    cur: str | None = None
    kept = dropped = unknown = 0

    for line in lines:
        if line.startswith("MAP:"):
            # MAP:TITLE:flags
            parts = line.split(":")
            cur = parts[1] if len(parts) > 1 else ""
            out.append(line)
            continue

        if cur is None or not is_nav_map(cur):
            out.append(line)
            continue

        m = sym_re.match(line)
        if not m:
            out.append(line)
            continue

        already = bool(m.group(1))
        payload = m.group(3)
        cm = coord_sym_re.match(payload)
        if cm:
            lon, lat = parse_lat_lon_tokens(cm.group(1), cm.group(2))
            ok = inside_clip(clip, lon, lat)
        else:
            name = payload.split(":")[0]
            if name not in lookups:
                unknown += 1
                out.append(line)
                continue
            lon, lat = lookups[name]
            ok = inside_clip(clip, lon, lat)

        if ok:
            if already and line.lstrip().startswith("//"):
                # strip a single leading //
                stripped = line.lstrip()
                out.append(stripped[2:] if stripped.startswith("//") else line)
            else:
                out.append(line)
            kept += 1
        else:
            if already:
                out.append(line)
            else:
                out.append("//" + line)
            dropped += 1

    GRP_PATH.write_bytes(("\n".join(out) + "\n").encode("cp1252"))
    print(f"GRpluginMaps NAV: keep={kept} deactivate={dropped} unknown_keep={unknown}")


def filter_asr(clip: Polygon, lookups: dict[str, tuple[float, float]]) -> None:
    for asr in sorted(ASR_DIR.glob("*.asr")):
        lines = asr.read_text(encoding="utf-8", errors="replace").splitlines()
        out: list[str] = []
        kept = dropped = unknown = 0
        changed = False
        for line in lines:
            if not any(line.startswith(p) for p in ASR_PREFIXES):
                out.append(line)
                continue
            name = line.split(":")[1]
            if name not in lookups:
                unknown += 1
                out.append(line)
                continue
            lon, lat = lookups[name]
            if inside_clip(clip, lon, lat):
                out.append(line)
                kept += 1
            else:
                dropped += 1
                changed = True
        if changed:
            asr.write_text("\n".join(out) + "\n", encoding="utf-8")
            print(f"{asr.name}: keep={kept} drop={dropped} unknown={unknown}")


def main() -> None:
    sct_path = find_sct()
    clip = buffer_polygon_nm(parse_esa_fir_polygon(TOPSKY_PATH), FIR_BUFFER_NM, FIR_SIMPLIFY_NM)
    print(
        f"Clip ESAA FIR (buffer={FIR_BUFFER_NM:.0f} NM) bounds "
        f"lon={clip.bounds[0]:.2f}..{clip.bounds[2]:.2f} "
        f"lat={clip.bounds[1]:.2f}..{clip.bounds[3]:.2f}"
    )
    lookups = load_sct_lookups(sct_path)
    print(f"SCT: {sct_path.name}  lookups: {len(lookups)}")
    filter_grplugin(clip, lookups)
    filter_asr(clip, lookups)


if __name__ == "__main__":
    main()

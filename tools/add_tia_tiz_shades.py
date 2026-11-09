"""Insert TIA/TIZ HIGHLIGHT fill maps into GRpluginMaps.txt from SCT ARTCC."""

from __future__ import annotations

import re
from collections import defaultdict
from pathlib import Path

from shapely.geometry import LineString
from shapely.ops import linemerge, polygonize

SCT_PATH = Path(
    r"C:\Users\maxlk\AppData\Roaming\EuroScope\ESAA-Sweden_20261029211836-261101-0001.sct"
)
GRP_PATH = Path(__file__).resolve().parents[1] / "Plugins" / "GRpluginMaps.txt"

coord_re = re.compile(
    r"([NS]\d{3}\.\d{2}\.\d{2}\.\d{3})\s+([EW]\d{3}\.\d{2}\.\d{2}\.\d{3})"
)


def dms_to_deg(hem: str, s: str) -> float:
    parts = s.split(".")
    d, m = int(parts[0]), int(parts[1])
    sec = int(parts[2]) + int(parts[3]) / 1000
    val = d + m / 60 + sec / 3600
    return -val if hem in "SW" else val


def parse_pt(ns: str, ew: str) -> tuple[float, float]:
    return (dms_to_deg(ew[0], ew[1:]), dms_to_deg(ns[0], ns[1:]))


def format_coord(lon: float, lat: float) -> str:
    def one(v: float, pos: str, neg: str) -> str:
        hem = pos if v >= 0 else neg
        v = abs(v)
        d = int(v)
        m = int((v - d) * 60)
        s = (v - d) * 3600 - m * 60
        si = int(s)
        f = int(round((s - si) * 1000))
        if f == 1000:
            f = 0
            si += 1
        if si == 60:
            si = 0
            m += 1
        if m == 60:
            m = 0
            d += 1
        return f"{hem}{d:03d}.{m:02d}.{si:02d}.{f:03d}"

    return f"{one(lat, 'N', 'S')} {one(lon, 'E', 'W')}"


def section(text: list[str], name: str) -> list[str]:
    start = next(i for i, l in enumerate(text) if l.strip() == name) + 1
    end = next(
        (
            j
            for j in range(start, len(text))
            if text[j].startswith("[") and text[j].strip().endswith("]")
        ),
        len(text),
    )
    return text[start:end]


def parse_artcc(lines: list[str], want_suffix: str) -> dict[str, list]:
    segs: dict[str, list] = defaultdict(list)
    cur = None
    for l in lines:
        if not l.strip():
            continue
        coords = coord_re.findall(l)
        before = l[: l.index(coords[0][0])].strip() if coords else l.strip()
        if before and not before.startswith("COLOR"):
            cur = before if before.split()[-1] == want_suffix else None
        if cur and len(coords) >= 2:
            segs[cur].append((parse_pt(*coords[0]), parse_pt(*coords[1])))
    return segs


def polys_for(segments):
    lines = [LineString([a, b]) for a, b in segments]
    return list(polygonize(linemerge(lines)))


def emit_map(mapname: str, color: str, items: dict) -> list[str]:
    out = [
        f"MAP:{mapname}:T",
        "HIDDEN",
        "FOLDER:AIRSPACE",
        "ASRDATA:TWR",
        f"COLOR:{color}",
        "ACTIVE:1",
    ]
    for _name, segs in sorted(items.items()):
        for p in polys_for(segs):
            coords = list(p.exterior.coords)
            if coords[0] == coords[-1]:
                coords = coords[:-1]
            out.append("COORDTYPE:OTHER:REGION")
            for lon, lat in coords:
                out.append(format_coord(lon, lat))
            lon, lat = coords[0]
            out.append(format_coord(lon, lat))
    out.append("")
    return out


def main() -> None:
    text = SCT_PATH.read_bytes().decode("latin-1", errors="replace").splitlines()
    tia = parse_artcc(section(text, "[ARTCC HIGH]"), "TIA")
    tiz = parse_artcc(section(text, "[ARTCC LOW]"), "TIZ")

    block: list[str] = []
    block.append("// All TIA fills (ARTCC HIGH), same highlight style as Stockholm TMA")
    block.extend(emit_map("TIA SHADE", "HIGHLIGHT/37", tia))
    block.append("// All TIZ fills (ARTCC LOW), same highlight style as Stockholm CTR")
    block.extend(emit_map("TIZ SHADE", "HIGHLIGHT/110", tiz))

    grp_text = GRP_PATH.read_text(encoding="utf-8")
    marker = "MAP:STOCKHOLM TMA:T"
    if "MAP:TIA SHADE:T" in grp_text:
        # Replace existing shade maps through STOCKHOLM TMA
        start = grp_text.index("// All TIA fills")
        end = grp_text.index(marker)
        grp_text = grp_text[:start] + "\n".join(block) + grp_text[end:]
        print(f"Replaced existing TIA/TIZ shade maps ({len(tia)} TIA, {len(tiz)} TIZ)")
    else:
        if marker not in grp_text:
            raise SystemExit("insert point MAP:STOCKHOLM TMA:T missing")
        grp_text = grp_text.replace(marker, "\n".join(block) + marker, 1)
        print(f"Inserted TIA/TIZ shade maps ({len(tia)} TIA, {len(tiz)} TIZ)")

    GRP_PATH.write_text(grp_text, encoding="utf-8")
    print(f"Wrote {GRP_PATH}")


if __name__ == "__main__":
    main()

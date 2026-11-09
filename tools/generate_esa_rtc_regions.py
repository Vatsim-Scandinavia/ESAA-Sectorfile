"""
Generate ESAA RTC REGIONS from GEO landmarks COAST, ISLANDS, LAKES.

Drawing order:
  1. Blue water fill tiled into 1° quads (COLOR_Landmark7) — avoids EuroScope zoom culling
  2. Green mainland from COAST, clipped and tiled like water (COLOR_Landmark6)
  3. Green islands, also tiled when large (COLOR_Landmark6)
  4. Blue lakes (COLOR_Landmark7)
"""

from __future__ import annotations

from pathlib import Path
import math
import re
from shapely.geometry import LineString, Point, Polygon, box
from shapely.ops import linemerge, polygonize, unary_union, snap

SCT_PATH = Path(r"C:\Users\maxlk\AppData\Roaming\EuroScope\ESAA-Sweden_20261029211836-261101-0001.sct")
BACKUP_PATH = SCT_PATH.with_name(SCT_PATH.stem + " - RTC_pre_regen.bak.sct")

MIN_LON, MIN_LAT, MAX_LON, MAX_LAT = 7.0, 54.0, 25.0, 72.0
BBOX = box(MIN_LON, MIN_LAT, MAX_LON, MAX_LAT)

# RTC colours (EuroScope: R + G*256 + B*65536).
# Land: 62.5% toward warmed green/yellow from raw mix → RGB(44,151,85)
# Water: mix of #0000d4/#1f4794/#4b2bc9 → RGB(35,38,187)
COLOR_WATER = "COLOR_Terrain7"
COLOR_WATER_RGB = (35, 38, 187)
COLOR_LAND = "COLOR_Terrain2"
COLOR_LAND_RGB = (44, 151, 85)
REGION_NAME = "ESAA RTC"

# Seeds used only for exclusive face classification (land XOR water).
LAND_SEEDS = [
    (18.07, 59.33),  # Stockholm
    (15.0, 62.0),  # mid Sweden
    (11.97, 57.71),  # Gothenburg
    (13.0, 55.6),  # Malmö / Skåne
    (10.75, 59.91),  # Oslo
    (9.5, 56.2),  # Jutland
    (9.92, 57.05),  # Aalborg
    (23.5, 61.5),  # Finland inland (east edge)
    (24.94, 60.17),  # Helsinki
    (22.15, 65.58),  # Luleå
    (20.25, 67.85),  # Kiruna
    (14.37, 67.28),  # Bodø
    (17.43, 68.44),  # Narvik
    (16.0, 66.0),
    (14.2, 65.3),
]

WATER_SEEDS = [
    (20.0, 58.5),  # Baltic
    (8.0, 57.0),  # North Sea
    (20.0, 63.0),  # Bothnia
    (10.0, 65.0),  # Norwegian Sea
    (22.0, 71.5),  # Barents
    (14.0, 54.5),  # south water
    (20.5, 60.2),  # Åland sea
    (23.0, 56.5),  # SE Baltic
    (12.0, 56.5),  # Kattegat
    (8.5, 66.0),
    (15.0, 71.5),
    (24.0, 58.0),
    (9.0, 68.0),
    (18.0, 71.0),
]

MIN_AREA_DEG2 = 1e-7
SIMPLIFY_TOL = 0.0002  # ~20 m-ish in deg

# EuroScope drops very large filled regions when zoomed in; tile water and
# land so each polygon stays small enough to remain visible (esp. north of ESPA).
WATER_TILE_DEG = 1.0
LAND_TILE_DEG = 1.0

coord_re = re.compile(
    r"([NS])(\d{3})\.(\d{2})\.(\d{2})\.(\d{3})\s+([EW])(\d{3})\.(\d{2})\.(\d{2})\.(\d{3})"
)


def parse_coord(m: re.Match) -> tuple[float, float]:
    hemi, d, mi, s, f = m.group(1), int(m.group(2)), int(m.group(3)), int(m.group(4)), int(m.group(5))
    lat = d + mi / 60 + (s + f / 1000) / 3600
    if hemi == "S":
        lat = -lat
    hemi, d, mi, s, f = m.group(6), int(m.group(7)), int(m.group(8)), int(m.group(9)), int(m.group(10))
    lon = d + mi / 60 + (s + f / 1000) / 3600
    if hemi == "W":
        lon = -lon
    return (lon, lat)


def format_coord(lon: float, lat: float) -> str:
    def one(val: float, pos: str, neg: str) -> str:
        hemi = pos if val >= 0 else neg
        val = abs(val)
        deg = int(val)
        rem = (val - deg) * 60
        minutes = int(rem)
        sec = (rem - minutes) * 60
        whole = int(sec)
        frac = int(round((sec - whole) * 1000))
        if frac == 1000:
            frac = 0
            whole += 1
        if whole == 60:
            whole = 0
            minutes += 1
        if minutes == 60:
            minutes = 0
            deg += 1
        return f"{hemi}{deg:03d}.{minutes:02d}.{whole:02d}.{frac:03d}"

    return f"{one(lat, 'N', 'S')} {one(lon, 'E', 'W')}"


def find_landmark_spans(text: list[str]) -> dict[str, tuple[int, int]]:
    """Return 1-based inclusive [start, end] line spans for COAST / ISLANDS / LAKES."""
    names = ("COAST", "ISLANDS", "LAKES")
    starts: dict[str, int] = {}
    for i, line in enumerate(text, start=1):
        for name in names:
            if line.startswith(f"ESAA Landmark {name}"):
                starts[name] = i
                break
    if set(starts) != set(names):
        raise RuntimeError(f"Missing landmark sections: {set(names) - set(starts)}")

    def section_end(start_1based: int) -> int:
        # GEO continuations are indented; the next named object starts at column 0.
        end = start_1based
        for idx in range(start_1based, len(text)):  # 0-based idx of following lines
            line = text[idx]
            if line.strip() == "[REGIONS]":
                break
            if line.strip() and not line[:1].isspace():
                break
            end = idx + 1
        while end > start_1based and not text[end - 1].strip():
            end -= 1
        return end

    return {name: (start, section_end(start)) for name, start in starts.items()}


def extract_segments(text: list[str], start: int, end: int) -> list[LineString]:
    segs: list[LineString] = []
    for line in text[start - 1 : end]:
        coords = [parse_coord(m) for m in coord_re.finditer(line)]
        if len(coords) >= 2:
            a, b = coords[0], coords[1]
            if a != b:
                segs.append(LineString([a, b]))
    return segs


def as_line_list(geom) -> list[LineString]:
    if geom is None or geom.is_empty:
        return []
    if geom.geom_type == "LineString":
        return [geom] if geom.length > 0 else []
    if geom.geom_type == "MultiLineString":
        return [g for g in geom.geoms if g.length > 0]
    if geom.geom_type == "GeometryCollection":
        out: list[LineString] = []
        for g in geom.geoms:
            out.extend(as_line_list(g))
        return out
    return []


def clip_lines(segs: list[LineString]) -> list[LineString]:
    out: list[LineString] = []
    for ls in segs:
        c = ls.intersection(BBOX)
        out.extend(as_line_list(c))
    return out


def merge_lines(segs: list[LineString]) -> list[LineString]:
    if not segs:
        return []
    return as_line_list(linemerge(segs))


def iter_polys(geom) -> list[Polygon]:
    if geom is None or geom.is_empty:
        return []
    if geom.geom_type == "Polygon":
        return [geom]
    if geom.geom_type == "MultiPolygon":
        return list(geom.geoms)
    if geom.geom_type == "GeometryCollection":
        out: list[Polygon] = []
        for g in geom.geoms:
            out.extend(iter_polys(g))
        return out
    return []


def close_open_against_bbox(lines: list[LineString]) -> list[Polygon]:
    boundary = LineString(
        [
            (MIN_LON, MIN_LAT),
            (MAX_LON, MIN_LAT),
            (MAX_LON, MAX_LAT),
            (MIN_LON, MAX_LAT),
            (MIN_LON, MIN_LAT),
        ]
    )
    unioned = snap(unary_union(list(lines) + [boundary]), boundary, 1e-7)
    return [p for p in polygonize(unioned) if p.area >= MIN_AREA_DEG2]


def classify_land_from_coast(coast_lines: list[LineString]) -> list[Polygon]:
    """Keep faces that contain land seeds and no water seeds.

    Faces that mix both (notably north Norway west of the clip edge) are left as
    water via the background rectangle.
    """
    faces = close_open_against_bbox(coast_lines)
    land: list[Polygon] = []
    for face in faces:
        has_land = any(face.contains(Point(x, y)) for x, y in LAND_SEEDS)
        has_water = any(face.contains(Point(x, y)) for x, y in WATER_SEEDS)
        if has_land and not has_water:
            land.append(face)
    return land


def island_polygons(island_lines: list[LineString]) -> list[Polygon]:
    polys: list[Polygon] = []
    opens: list[LineString] = []
    for g in island_lines:
        if g.is_ring or g.coords[0] == g.coords[-1]:
            try:
                p = Polygon(g)
                if not p.is_valid:
                    p = p.buffer(0)
                for q in iter_polys(p.intersection(BBOX)):
                    if q.area >= MIN_AREA_DEG2:
                        polys.append(q)
            except Exception:
                continue
        else:
            opens.append(g)

    # Open fragments clipped by the rectangle: keep only small faces created
    # against the bbox that are tightly bound by the fragment.
    if opens:
        for face in close_open_against_bbox(opens):
            if face.area >= BBOX.area * 0.05:
                continue
            for g in opens:
                if face.boundary.intersection(g).length >= g.length * 0.5:
                    if face.area >= MIN_AREA_DEG2:
                        polys.append(face)
                    break
    return polys


def lake_polygons(lake_lines: list[LineString]) -> list[Polygon]:
    polys: list[Polygon] = []
    for g in lake_lines:
        coords = list(g.coords)
        if g.is_ring or coords[0] == coords[-1]:
            ring = coords
        elif Point(coords[0]).distance(Point(coords[-1])) < 1e-4:
            ring = coords + [coords[0]]
        else:
            continue
        try:
            p = Polygon(ring)
            if not p.is_valid:
                p = p.buffer(0)
            for q in iter_polys(p.intersection(BBOX)):
                if q.area >= MIN_AREA_DEG2:
                    polys.append(q)
        except Exception:
            continue
    return polys


def simplify_poly(p: Polygon) -> Polygon:
    s = p.simplify(SIMPLIFY_TOL, preserve_topology=True)
    polys = iter_polys(s)
    if not polys:
        return p
    return max(polys, key=lambda q: q.area)


def exterior_coords(p: Polygon) -> list[tuple[float, float]]:
    coords = list(p.exterior.coords)
    if len(coords) > 1 and coords[0] == coords[-1]:
        coords = coords[:-1]
    return coords


def emit_region(coords: list[tuple[float, float]], color: str) -> list[str]:
    if len(coords) < 3:
        return []
    lines = [f"REGIONNAME {REGION_NAME}"]
    lines.append(f"{color}            {format_coord(*coords[0])}")
    for lon, lat in coords[1:]:
        lines.append(f"                           {format_coord(lon, lat)}")
    return lines


def water_background_tiles(
    tile_deg: float = WATER_TILE_DEG,
) -> list[list[tuple[float, float]]]:
    """Split the RTC water rectangle into a lon/lat grid of small quads."""
    tiles: list[list[tuple[float, float]]] = []
    lon = MIN_LON
    while lon < MAX_LON - 1e-12:
        lon2 = min(lon + tile_deg, MAX_LON)
        lat = MIN_LAT
        while lat < MAX_LAT - 1e-12:
            lat2 = min(lat + tile_deg, MAX_LAT)
            tiles.append(
                [
                    (lon, lat),
                    (lon2, lat),
                    (lon2, lat2),
                    (lon, lat2),
                ]
            )
            lat = lat2
        lon = lon2
    return tiles


def tile_polygon(poly: Polygon, tile_deg: float = LAND_TILE_DEG) -> list[Polygon]:
    """Intersect a land/island polygon with the same lon/lat grid as water."""
    minx, miny, maxx, maxy = poly.bounds
    lon0 = MIN_LON + math.floor((minx - MIN_LON) / tile_deg) * tile_deg
    lat0 = MIN_LAT + math.floor((miny - MIN_LAT) / tile_deg) * tile_deg
    pieces: list[Polygon] = []
    lon = lon0
    while lon < maxx - 1e-12:
        lon2 = lon + tile_deg
        lat = lat0
        while lat < maxy - 1e-12:
            lat2 = lat + tile_deg
            inter = poly.intersection(box(lon, lat, min(lon2, MAX_LON), min(lat2, MAX_LAT)))
            for q in iter_polys(inter):
                if q.area >= MIN_AREA_DEG2:
                    pieces.append(q)
            lat = lat2
        lon = lon2
    return pieces if pieces else [poly]


def strip_custom_rtc_color_defines(text: list[str]) -> list[str]:
    """Remove obsolete COLOR_RTC_* defines if present."""
    out = [
        line
        for line in text
        if not line.strip().startswith("#define COLOR_RTC_Land")
        and not line.strip().startswith("#define COLOR_RTC_Water")
    ]
    removed = len(text) - len(out)
    if removed:
        print(f"Removed {removed} custom COLOR_RTC_* define(s)")
    return out


def es_color_int(rgb: tuple[int, int, int]) -> int:
    r, g, b = rgb
    return r + (g << 8) + (b << 16)


def ensure_color_define(text: list[str], name: str, rgb: tuple[int, int, int]) -> list[str]:
    """Set or insert a #define COLOR_* value."""
    value = es_color_int(rgb)
    line = f"#define {name}  {value}"
    prefix = f"#define {name}"
    out: list[str] = []
    found = False
    for l in text:
        if l.strip().startswith(prefix):
            out.append(line)
            found = True
        else:
            out.append(l)
    if not found:
        insert_at = None
        for i, l in enumerate(out):
            if l.strip().startswith("#define COLOR_Terrain"):
                insert_at = i + 1
        if insert_at is None:
            for i, l in enumerate(out):
                if l.strip().startswith("#define COLOR_"):
                    insert_at = i + 1
                    break
        if insert_at is None:
            insert_at = 0
        out.insert(insert_at, line)
    print(f"{name} = {value} RGB{rgb}")
    return out


def ensure_rtc_color_defines(text: list[str]) -> list[str]:
    text = ensure_color_define(text, COLOR_LAND, COLOR_LAND_RGB)
    text = ensure_color_define(text, COLOR_WATER, COLOR_WATER_RGB)
    return text


def find_rtc_span(text: list[str]) -> tuple[int, int]:
    regions_idx = None
    for i, line in enumerate(text):
        if line.strip() == "[REGIONS]":
            regions_idx = i
            break
    if regions_idx is None:
        raise RuntimeError("[REGIONS] not found")

    i = regions_idx + 1
    while i < len(text) and not text[i].strip():
        i += 1

    if i >= len(text) or not text[i].startswith(f"REGIONNAME {REGION_NAME}"):
        return regions_idx + 1, regions_idx + 1

    start = i
    while i < len(text):
        line = text[i]
        if line.startswith("REGIONNAME "):
            if line.startswith(f"REGIONNAME {REGION_NAME}"):
                i += 1
                continue
            break
        if line.startswith("[") and line.strip().endswith("]"):
            break
        i += 1
    return start, i


def main() -> None:
    raw = SCT_PATH.read_bytes()
    text = raw.decode("latin-1", errors="replace").splitlines()
    text = strip_custom_rtc_color_defines(text)
    text = ensure_rtc_color_defines(text)

    print("Extracting landmark segments...")
    spans = find_landmark_spans(text)
    coast = clip_lines(extract_segments(text, *spans["COAST"]))
    islands = clip_lines(extract_segments(text, *spans["ISLANDS"]))
    lakes = clip_lines(extract_segments(text, *spans["LAKES"]))
    print(
        f"  spans COAST={spans['COAST']} ISLANDS={spans['ISLANDS']} LAKES={spans['LAKES']}"
    )
    print(f"  clipped segments coast={len(coast)} islands={len(islands)} lakes={len(lakes)}")

    coast_lines = merge_lines(coast)
    island_lines = merge_lines(islands)
    lake_lines = merge_lines(lakes)

    print("Building mainland from COAST...")
    land_polys = [simplify_poly(p) for p in classify_land_from_coast(coast_lines)]
    print(f"  land faces: {len(land_polys)} area={sum(p.area for p in land_polys):.3f}")

    print("Building ISLANDS...")
    island_polys = [simplify_poly(p) for p in island_polygons(island_lines)]
    print(f"  island polys: {len(island_polys)} area={sum(p.area for p in island_polys):.3f}")

    print("Building LAKES...")
    lake_polys = [simplify_poly(p) for p in lake_polygons(lake_lines)]
    print(f"  lake polys: {len(lake_polys)} area={sum(p.area for p in lake_polys):.3f}")

    print(f"Tiling mainland into {LAND_TILE_DEG}° cells...")
    land_tiles: list[Polygon] = []
    for p in land_polys:
        land_tiles.extend(tile_polygon(p))
    print(f"  land tiles: {len(land_tiles)} (from {len(land_polys)} faces)")

    print(f"Tiling islands into {LAND_TILE_DEG}° cells...")
    island_tiles: list[Polygon] = []
    for p in island_polys:
        island_tiles.extend(tile_polygon(p))
    print(f"  island tiles: {len(island_tiles)} (from {len(island_polys)} polys)")

    out_lines: list[str] = []
    water_tiles = water_background_tiles()
    print(f"Water background tiles: {len(water_tiles)} ({WATER_TILE_DEG}°)")
    for tile in water_tiles:
        out_lines.extend(emit_region(tile, COLOR_WATER))
    for p in sorted(land_tiles, key=lambda x: -x.area):
        out_lines.extend(emit_region(exterior_coords(simplify_poly(p)), COLOR_LAND))
    for p in sorted(island_tiles, key=lambda x: -x.area):
        out_lines.extend(emit_region(exterior_coords(simplify_poly(p)), COLOR_LAND))
    for p in sorted(lake_polys, key=lambda x: -x.area):
        out_lines.extend(emit_region(exterior_coords(p), COLOR_WATER))

    n_regions = sum(1 for l in out_lines if l.startswith("REGIONNAME"))
    print(f"Generated {n_regions} REGIONNAME blocks, {len(out_lines)} lines")

    start, end = find_rtc_span(text)
    print(f"Replacing RTC region lines [{start + 1}..{end}] ({end - start} old lines)")

    new_text = text[:start] + out_lines + text[end:]

    if not BACKUP_PATH.exists():
        BACKUP_PATH.write_bytes(raw)
        print(f"Backup written: {BACKUP_PATH}")

    newline = b"\r\n" if b"\r\n" in raw else b"\n"
    payload = newline.join(line.encode("latin-1", errors="replace") for line in new_text)
    if raw.endswith(b"\n") or raw.endswith(b"\r\n"):
        payload += newline
    SCT_PATH.write_bytes(payload)
    print(f"Updated: {SCT_PATH}")


if __name__ == "__main__":
    main()

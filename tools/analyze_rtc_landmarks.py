from pathlib import Path
import re
from shapely.geometry import LineString, box, Polygon
from shapely.ops import linemerge

sct = Path(r"C:\Users\maxlk\AppData\Roaming\EuroScope\ESAA-Sweden_20261029211836-261101-0001.sct")
text = sct.read_text(encoding="latin-1", errors="replace").splitlines()
coord_re = re.compile(
    r"([NS])(\d{3})\.(\d{2})\.(\d{2})\.(\d{3})\s+([EW])(\d{3})\.(\d{2})\.(\d{2})\.(\d{3})"
)


def parse_coord(m):
    hemi, d, mi, s, f = m.group(1), int(m.group(2)), int(m.group(3)), int(m.group(4)), int(m.group(5))
    lat = d + mi / 60 + (s + f / 1000) / 3600
    if hemi == "S":
        lat = -lat
    hemi, d, mi, s, f = m.group(6), int(m.group(7)), int(m.group(8)), int(m.group(9)), int(m.group(10))
    lon = d + mi / 60 + (s + f / 1000) / 3600
    if hemi == "W":
        lon = -lon
    return (lon, lat)


def extract_segments(start, end):
    segs = []
    for line in text[start - 1 : end]:
        coords = [parse_coord(m) for m in coord_re.finditer(line)]
        if len(coords) >= 2:
            a, b = coords[0], coords[1]
            if a != b:
                segs.append(LineString([a, b]))
    return segs


def clip_lines(segs, bbox):
    out = []
    for ls in segs:
        c = ls.intersection(bbox)
        if c.is_empty:
            continue
        if c.geom_type == "LineString":
            if c.length > 0:
                out.append(c)
        elif c.geom_type == "MultiLineString":
            out.extend([g for g in c.geoms if g.length > 0])
        elif c.geom_type == "GeometryCollection":
            for g in c.geoms:
                if g.geom_type == "LineString" and g.length > 0:
                    out.append(g)
                elif g.geom_type == "MultiLineString":
                    out.extend([x for x in g.geoms if x.length > 0])
    return out


def merge_stats(segs, name):
    ml = linemerge(segs)
    geoms = [ml] if ml.geom_type == "LineString" else list(ml.geoms)
    closed = sum(1 for g in geoms if g.is_ring or g.coords[0] == g.coords[-1])
    open_ = len(geoms) - closed
    lengths = sorted((g.length for g in geoms), reverse=True)[:5]
    print(f"{name}: parts={len(geoms)} closed={closed} open={open_} top_len={[round(x, 3) for x in lengths]}")
    opens = [g for g in geoms if not (g.is_ring or g.coords[0] == g.coords[-1])]
    near = 0
    samples = []
    for g in opens[:30]:
        for p in (g.coords[0], g.coords[-1]):
            x, y = p
            on = abs(x - 7) < 1e-6 or abs(x - 25) < 1e-6 or abs(y - 54) < 1e-6 or abs(y - 72) < 1e-6
            if on:
                near += 1
            samples.append((round(x, 4), round(y, 4), "bbox" if on else "in"))
    print(f"  open endpoints on bbox among first 30 opens: {near}")
    print(f"  sample endpoints: {samples[:12]}")
    return geoms


def rings_to_polys(geoms):
    polys = []
    for g in geoms:
        if g.is_ring or g.coords[0] == g.coords[-1]:
            try:
                p = Polygon(g)
                if p.is_valid and p.area > 0:
                    polys.append(p)
                elif not p.is_valid:
                    p2 = p.buffer(0)
                    if not p2.is_empty and p2.area > 0:
                        if p2.geom_type == "Polygon":
                            polys.append(p2)
                        else:
                            polys.extend([x for x in p2.geoms if x.area > 0])
            except Exception:
                pass
    return polys


coast = extract_segments(57116, 91686)
islands = extract_segments(91687, 123635)
lakes = extract_segments(123636, 126285)
print("segments", len(coast), len(islands), len(lakes))

bbox = box(7.0, 54.0, 25.0, 72.0)
c_c = clip_lines(coast, bbox)
c_i = clip_lines(islands, bbox)
c_l = clip_lines(lakes, bbox)
print("clipped segs", len(c_c), len(c_i), len(c_l))

cg = merge_stats(c_c, "COAST")
ig = merge_stats(c_i, "ISLANDS")
lg = merge_stats(c_l, "LAKES")

ip = rings_to_polys(ig)
lp = rings_to_polys(lg)
print("island polys", len(ip), "area", round(sum(p.area for p in ip), 3))
print("lake polys", len(lp), "area", round(sum(p.area for p in lp), 3))
print("island open leftover", sum(1 for g in ig if not (g.is_ring or g.coords[0] == g.coords[-1])))
print("lake open leftover", sum(1 for g in lg if not (g.is_ring or g.coords[0] == g.coords[-1])))

# Check if coast alone + bbox boundary polygonizes into land/water
from shapely.ops import polygonize, unary_union

boundary = LineString([(7, 54), (25, 54), (25, 72), (7, 72), (7, 54)])
# snap ends lightly
merged = linemerge(c_c)
coast_lines = [merged] if merged.geom_type == "LineString" else list(merged.geoms)
all_lines = coast_lines + [boundary]
# also add island closed rings as lines? for classification later
poly_candidates = list(polygonize(unary_union(all_lines)))
print("polygonize coast+bbox:", len(poly_candidates), "area sum", round(sum(p.area for p in poly_candidates), 3), "bbox area", round(bbox.area, 3))
# classify by testing a known sea point (Baltic approx 58.5N 20E) and land (Stockholm 59.33N 18.07E)
sea = next((p for p in poly_candidates if p.contains(__import__("shapely").geometry.Point(20.0, 58.5))), None)
land = next((p for p in poly_candidates if p.contains(__import__("shapely").geometry.Point(18.07, 59.33))), None)
print("sea poly area", None if sea is None else round(sea.area, 3))
print("land poly area", None if land is None else round(land.area, 3))
print("num polys containing stockholm", sum(1 for p in poly_candidates if p.contains(__import__("shapely").geometry.Point(18.07, 59.33))))
print("num polys containing baltic", sum(1 for p in poly_candidates if p.contains(__import__("shapely").geometry.Point(20.0, 58.5))))
print("num polys containing mid sweden", sum(1 for p in poly_candidates if p.contains(__import__("shapely").geometry.Point(15.0, 62.0))))
print("num polys containing north sea", sum(1 for p in poly_candidates if p.contains(__import__("shapely").geometry.Point(8.0, 57.0))))

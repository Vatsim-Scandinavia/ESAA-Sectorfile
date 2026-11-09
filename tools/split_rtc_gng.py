from pathlib import Path


def parse_polys(lines):
    polys = []
    i = 0
    while i < len(lines):
        if lines[i].startswith("COLOR_"):
            color = lines[i]
            coords = []
            i += 1
            while i < len(lines) and not lines[i].startswith("COLOR_"):
                coords.append(lines[i])
                i += 1
            polys.append((color, coords))
        else:
            i += 1
    return polys


def emit(polys):
    out = []
    for color, coords in polys:
        out.append(color)
        out.extend(coords)
    return "\n".join(out) + "\n"


def nbytes(ps):
    return len(emit(ps).encode("utf-8"))


src = Path(__file__).with_name("ESAA_RTC_GNG.txt")
polys = parse_polys(src.read_text(encoding="utf-8").splitlines())
water = [p for p in polys if p[0] == "COLOR_Landmark7"]
land = [p for p in polys if p[0] == "COLOR_Landmark6"]

full = nbytes(polys)
t1 = full // 3
t2 = 2 * full // 3

rtc1 = list(water)
for poly in land:
    if nbytes(rtc1) < t1:
        rtc1.append(poly)
    else:
        break
n1 = len(rtc1) - len(water)
rest = land[n1:]

rtc2 = []
for poly in rest:
    if nbytes(rtc1) + nbytes(rtc2) < t2:
        rtc2.append(poly)
    else:
        break
rtc3 = rest[len(rtc2) :]

parts = [rtc1, rtc2, rtc3]
for i, part in enumerate(parts, 1):
    p = Path(__file__).with_name(f"ESAA_RTC{i}_GNG.txt")
    p.write_text(emit(part), encoding="utf-8")
    w = sum(1 for c, _ in part if c == "COLOR_Landmark7")
    l = sum(1 for c, _ in part if c == "COLOR_Landmark6")
    lines = sum(1 for _ in p.open(encoding="utf-8"))
    print(f"RTC{i}: {p.resolve()}")
    print(f"  polys={len(part)} water={w} land={l} bytes={p.stat().st_size} lines={lines}")

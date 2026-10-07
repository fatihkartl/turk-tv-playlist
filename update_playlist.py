import json, re, urllib.request
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parent
CFG = json.loads((ROOT / "channels.json").read_text(encoding="utf-8"))
SOURCE = CFG["source"]

def base_id(raw):
    return raw.split("@", 1)[0].strip()

def resolution(text):
    m = re.search(r"\((\d{3,4})p\)", text)
    return int(m.group(1)) if m else 0

def host_allowed(url, allowed):
    host = (urlparse(url).hostname or "").lower()
    return any(host == x.lower() or host.endswith("." + x.lower()) for x in allowed)

def parse_source(text):
    lines = text.splitlines()
    out = []
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        if not line.startswith("#EXTINF"):
            i += 1
            continue
        m = re.search(r'tvg-id="([^"]*)"', line)
        tvg = base_id(m.group(1)) if m else ""
        extras = []
        j = i + 1
        while j < len(lines) and lines[j].strip().startswith("#"):
            extras.append(lines[j].strip())
            j += 1
        url = lines[j].strip() if j < len(lines) else ""
        out.append({"id": tvg, "extinf": line, "extras": extras, "url": url, "resolution": resolution(line)})
        i = j + 1
    return out

req = urllib.request.Request(SOURCE, headers={"User-Agent": "Mozilla/5.0"})
with urllib.request.urlopen(req, timeout=30) as r:
    upstream = parse_source(r.read().decode("utf-8", "replace"))

by_id = {}
for e in upstream:
    by_id.setdefault(e["id"], []).append(e)

selected = []
for ch in CFG["channels"]:
    candidates = []
    for e in by_id.get(ch["id"], []):
        if e["url"].startswith(("http://", "https://")) and host_allowed(e["url"], ch["trusted_hosts"]):
            candidates.append({
                "url": e["url"],
                "resolution": e["resolution"],
                "source": "upstream",
                "not24": "[Not 24/7]" in e["extinf"],
                "geo": "[Geo-blocked]" in e["extinf"]
            })
    for fb in ch.get("fallbacks", []):
        if host_allowed(fb["url"], ch["trusted_hosts"]):
            candidates.append({
                "url": fb["url"],
                "resolution": int(fb.get("resolution", 0)),
                "source": "fallback",
                "not24": False,
                "geo": False
            })
    if not candidates:
        continue

    def score(x):
        # Kalite öncelikli; HTTPS ve 24/7 görünen akışlara küçük bonus.
        return (
            x["resolution"],
            1 if x["url"].startswith("https://") else 0,
            0 if x["not24"] else 1,
            0 if x["geo"] else 1,
            1 if x["source"] == "upstream" else 0,
        )

    best = max(candidates, key=score)
    selected.append({**ch, **best})

def write_playlist(path, fhd_only=False):
    lines = ["#EXTM3U", "# Otomatik üretilir; elle düzenlemeyin.", f"# Kaynak: {SOURCE}", ""]
    for e in selected:
        if fhd_only and e["resolution"] < 1080:
            continue
        res = f" [{e['resolution']}p]" if e["resolution"] else ""
        lines.append(f'#EXTINF:-1 tvg-id="{e["id"]}" group-title="{e["group"]}",{e["name"]}{res}')
        lines.append(e["url"])
        lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")

write_playlist(ROOT / "turkiye_temiz.m3u", False)
write_playlist(ROOT / "turkiye_fhd_auto.m3u", True)
print(f"{len(selected)} kanal seçildi.")

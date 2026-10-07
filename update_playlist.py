import json
import re
import time
import urllib.request
from http.cookiejar import CookieJar
from pathlib import Path
from urllib.parse import urljoin, urlparse
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parent
CFG = json.loads((ROOT / "channels.json").read_text(encoding="utf-8"))
SOURCE = CFG["source"]
LOGO_SOURCE = "https://iptv-org.github.io/api/logos.json"
EPG_URL = "https://raw.githubusercontent.com/fatihkartl/turk-tv-playlist/main/epg_turkiye.xml"

USER_AGENT = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/154 Safari/537.36"
TIMEOUT = 10
RETRIES = 2
MAX_PLAYLIST_BYTES = 2_000_000
MAX_JSON_BYTES = 20_000_000
SEGMENT_PROBE_BYTES = 4096

cookie_jar = CookieJar()
opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cookie_jar))

def base_id(raw):
    return raw.split("@", 1)[0].strip()

def resolution(text):
    m = re.search(r"\((\d{3,4})p\)", text)
    if not m:
        m = re.search(r"\[(\d{3,4})p\]", text)
    return int(m.group(1)) if m else 0

def host_allowed(url, allowed):
    host = (urlparse(url).hostname or "").lower()
    return any(host == x.lower() or host.endswith("." + x.lower()) for x in allowed)

def request_bytes(url, timeout=TIMEOUT, byte_range=None, max_bytes=MAX_PLAYLIST_BYTES):
    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "*/*",
        "Cache-Control": "no-cache",
    }
    if byte_range:
        headers["Range"] = byte_range
    req = urllib.request.Request(url, headers=headers)
    with opener.open(req, timeout=timeout) as r:
        status = getattr(r, "status", 200)
        limit = SEGMENT_PROBE_BYTES if byte_range else max_bytes
        data = r.read(limit)
        return status, data, r.geturl(), r.headers.get("Content-Type", "")

def fetch_text(url, max_bytes=MAX_PLAYLIST_BYTES):
    status, data, final_url, ctype = request_bytes(url, max_bytes=max_bytes)
    if status not in (200, 206):
        raise RuntimeError(f"HTTP {status}")
    text = data.decode("utf-8", "replace").lstrip("\ufeff")
    return text, final_url, ctype

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
        out.append({
            "id": tvg,
            "extinf": line,
            "extras": extras,
            "url": url,
            "resolution": resolution(line),
        })
        i = j + 1
    return out

def parse_previous(path):
    if not path.exists():
        return {}
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    out = {}
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        if line.startswith("#EXTINF"):
            m = re.search(r'tvg-id="([^"]+)"', line)
            if m:
                tvg = m.group(1)
                lm = re.search(r'tvg-logo="([^"]+)"', line)
                j = i + 1
                while j < len(lines) and lines[j].strip().startswith("#"):
                    j += 1
                url = lines[j].strip() if j < len(lines) else ""
                if url.startswith(("http://", "https://")):
                    out[tvg] = {
                        "url": url,
                        "resolution": resolution(line),
                        "logo": lm.group(1) if lm else "",
                    }
                i = j
        i += 1
    return out

def parse_master_variants(text, base_url):
    variants = []
    lines = [x.strip() for x in text.splitlines()]
    for i, line in enumerate(lines):
        if not line.startswith("#EXT-X-STREAM-INF:"):
            continue
        attrs = line.split(":", 1)[1]
        height = 0
        bandwidth = 0
        m = re.search(r'RESOLUTION=\d+x(\d+)', attrs)
        if m:
            height = int(m.group(1))
        m = re.search(r'BANDWIDTH=(\d+)', attrs)
        if m:
            bandwidth = int(m.group(1))
        j = i + 1
        while j < len(lines) and (not lines[j] or lines[j].startswith("#")):
            j += 1
        if j < len(lines):
            variants.append((height, bandwidth, urljoin(base_url, lines[j])))
    variants.sort(reverse=True)
    return variants

def first_media_uri(text, base_url):
    lines = [x.strip() for x in text.splitlines()]
    for line in lines:
        if not line:
            continue
        if not line.startswith("#"):
            return urljoin(base_url, line)
        if line.startswith(("#EXT-X-PART:", "#EXT-X-MAP:")):
            m = re.search(r'URI="([^"]+)"', line)
            if m:
                return urljoin(base_url, m.group(1))
    return None

def check_hls_once(url, depth=0):
    text, final_url, _ = fetch_text(url)
    if "#EXTM3U" not in text[:4096]:
        return False, 0, "not-m3u8"

    variants = parse_master_variants(text, final_url)
    if variants and depth < 2:
        detected = variants[0][0]
        ok, child_res, detail = check_hls_once(variants[0][2], depth + 1)
        return ok, max(detected, child_res), f"master->{detail}"

    if "#EXTINF" not in text and "#EXT-X-PART" not in text and "#EXT-X-MAP" not in text:
        return False, 0, "no-media-tags"

    media_url = first_media_uri(text, final_url)
    if not media_url:
        return False, 0, "no-media-uri"

    try:
        status, data, _, _ = request_bytes(
            media_url,
            timeout=TIMEOUT,
            byte_range=f"bytes=0-{SEGMENT_PROBE_BYTES - 1}",
        )
        if status not in (200, 206) or not data:
            return False, 0, f"segment-http-{status}"
        prefix = data[:256].lstrip().lower()
        if prefix.startswith(b"<html") or prefix.startswith(b"<!doctype html"):
            return False, 0, "segment-is-html"
    except Exception as exc:
        return False, 0, f"segment-error:{type(exc).__name__}"

    return True, 0, "playlist+segment-ok"

def check_hls(url):
    last = "unknown"
    detected = 0
    for attempt in range(RETRIES):
        try:
            ok, detected, detail = check_hls_once(url)
            if ok:
                return True, detected, detail
            last = detail
        except Exception as exc:
            last = f"{type(exc).__name__}:{str(exc)[:120]}"
        if attempt + 1 < RETRIES:
            time.sleep(1.5)
    return False, detected, last

def choose_logo_map(channel_ids, previous):
    fallback = {cid: previous.get(cid, {}).get("logo", "") for cid in channel_ids}
    try:
        text, _, _ = fetch_text(LOGO_SOURCE, max_bytes=MAX_JSON_BYTES)
        entries = json.loads(text)
    except Exception as exc:
        print(f"Logo API alınamadı, önceki logolar korunuyor: {exc}")
        return fallback

    candidates = {cid: [] for cid in channel_ids}
    format_rank = {"PNG": 6, "WEBP": 5, "JPEG": 4, "JPG": 4, "SVG": 3, "AVIF": 2}

    for item in entries:
        cid = item.get("channel")
        if cid not in candidates or not item.get("in_use", False):
            continue
        url = item.get("url") or ""
        if not url.startswith("https://"):
            continue
        tags = {str(x).lower() for x in (item.get("tags") or [])}
        score = (
            1 if item.get("feed") in (None, "") else 0,
            format_rank.get(str(item.get("format") or "").upper(), 0),
            1 if "horizontal" in tags else 0,
            int(item.get("width") or 0) * int(item.get("height") or 0),
        )
        candidates[cid].append((score, url))

    result = {}
    for cid in channel_ids:
        if candidates[cid]:
            candidates[cid].sort(reverse=True)
            result[cid] = candidates[cid][0][1]
        else:
            result[cid] = fallback.get(cid, "")
    return result

req = urllib.request.Request(SOURCE, headers={"User-Agent": USER_AGENT})
with opener.open(req, timeout=30) as r:
    upstream = parse_source(r.read().decode("utf-8", "replace"))

by_id = {}
for entry in upstream:
    by_id.setdefault(entry["id"], []).append(entry)

previous = parse_previous(ROOT / "turkiye_temiz.m3u")
logo_map = choose_logo_map({c["id"] for c in CFG["channels"]}, previous)

selected = []
report_rows = []

for ch in CFG["channels"]:
    candidates = []
    seen_urls = set()

    for entry in by_id.get(ch["id"], []):
        if (
            entry["url"].startswith(("http://", "https://"))
            and host_allowed(entry["url"], ch["trusted_hosts"])
            and entry["url"] not in seen_urls
        ):
            seen_urls.add(entry["url"])
            candidates.append({
                "url": entry["url"],
                "resolution": entry["resolution"],
                "source": "upstream",
                "not24": "[Not 24/7]" in entry["extinf"],
                "geo": "[Geo-blocked]" in entry["extinf"],
            })

    for fb in ch.get("fallbacks", []):
        if host_allowed(fb["url"], ch["trusted_hosts"]) and fb["url"] not in seen_urls:
            seen_urls.add(fb["url"])
            candidates.append({
                "url": fb["url"],
                "resolution": int(fb.get("resolution", 0)),
                "source": "fallback",
                "not24": False,
                "geo": False,
            })

    def score(item):
        return (
            item["resolution"],
            1 if item["url"].startswith("https://") else 0,
            0 if item["not24"] else 1,
            0 if item["geo"] else 1,
            1 if item["source"] == "upstream" else 0,
        )

    candidates.sort(key=score, reverse=True)
    checks = []
    chosen = None

    for cand in candidates:
        ok, detected_res, detail = check_hls(cand["url"])
        checks.append({
            "url": cand["url"],
            "ok": ok,
            "detail": detail,
            "declared_resolution": cand["resolution"],
            "detected_resolution": detected_res,
        })
        if ok:
            cand["resolution"] = max(cand["resolution"], detected_res)
            cand["health"] = "verified"
            chosen = cand
            break

    if chosen is None:
        # Fail-safe: doğrulanamayan yeni URL'ye geçme.
        # Mevcut playlist URL'sini değiştirmeden koru.
        old = previous.get(ch["id"])
        if old and host_allowed(old["url"], ch["trusted_hosts"]):
            chosen = {
                "url": old["url"],
                "resolution": old.get("resolution", 0),
                "source": "previous",
                "not24": False,
                "geo": any(x.get("geo") for x in candidates),
                "health": "kept-previous-unverified",
            }

    if chosen:
        selected.append({**ch, **chosen, "logo": logo_map.get(ch["id"], "")})
        status = chosen["health"]
        chosen_url = chosen["url"]
    else:
        status = "skipped-no-verified-stream"
        chosen_url = ""

    report_rows.append({
        "id": ch["id"],
        "name": ch["name"],
        "status": status,
        "chosen_url": chosen_url,
        "checks": checks,
    })

def write_playlist(path, fhd_only=False):
    lines = [
        f'#EXTM3U x-tvg-url="{EPG_URL}" url-tvg="{EPG_URL}"',
        "# Otomatik üretilir; elle düzenlemeyin.",
        f"# Kaynak: {SOURCE}",
        "",
    ]
    for entry in selected:
        if fhd_only and entry["resolution"] < 1080:
            continue
        res = f" [{entry['resolution']}p]" if entry["resolution"] else ""
        logo = f' tvg-logo="{entry["logo"]}"' if entry.get("logo") else ""
        lines.append(
            f'#EXTINF:-1 tvg-id="{entry["id"]}"{logo} group-title="{entry["group"]}",{entry["name"]}{res}'
        )
        lines.append(entry["url"])
        lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")

write_playlist(ROOT / "turkiye_temiz.m3u", False)
write_playlist(ROOT / "turkiye_fhd_auto.m3u", True)

verified = sum(1 for x in report_rows if x["status"] == "verified")
kept = sum(1 for x in report_rows if x["status"] == "kept-previous-unverified")
skipped = sum(1 for x in report_rows if x["status"] == "skipped-no-verified-stream")

report = {
    "generated_at_utc": datetime.now(timezone.utc).isoformat(),
    "source": SOURCE,
    "logo_source": LOGO_SOURCE,
    "summary": {
        "configured": len(CFG["channels"]),
        "selected": len(selected),
        "verified_now": verified,
        "kept_previous_unverified": kept,
        "skipped": skipped,
        "logos_attached": sum(1 for x in selected if x.get("logo")),
    },
    "channels": report_rows,
}

(ROOT / "health_report.json").write_text(
    json.dumps(report, ensure_ascii=False, indent=2),
    encoding="utf-8",
)

print(
    f"{len(selected)} kanal seçildi | "
    f"{verified} şimdi doğrulandı | {kept} önceki URL korundu | "
    f"{skipped} atlandı | {report['summary']['logos_attached']} logo"
)

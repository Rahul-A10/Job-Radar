"""Reads careers.json, fetches every listed career page, writes jobs.json."""
import json, hashlib, html, re, datetime as dt, urllib.parse as up
import requests
from bs4 import BeautifulSoup

UA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/124 Safari/537.36"}
NOW = dt.datetime.now(dt.timezone.utc)
ISO = NOW.isoformat(timespec="seconds")


def jid(u): return hashlib.sha1(u.encode()).hexdigest()[:12]
def text(h): return re.sub(r"\s+", " ", BeautifulSoup(html.unescape(h or ""), "html.parser").get_text(" ")).strip()[:1500]


def greenhouse(slug):
    r = requests.get(f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs?content=true", headers=UA, timeout=30)
    r.raise_for_status()
    return [dict(title=j["title"], url=j["absolute_url"], location=(j.get("location") or {}).get("name", ""),
                 desc=text(j.get("content"))) for j in r.json()["jobs"]]


def lever(slug):
    r = requests.get(f"https://api.lever.co/v0/postings/{slug}?mode=json", headers=UA, timeout=30)
    r.raise_for_status()
    return [dict(title=j["text"], url=j["hostedUrl"], location=(j.get("categories") or {}).get("location", ""),
                 desc=(j.get("descriptionPlain") or "")[:1500]) for j in r.json()]


def workday(url):
    u = up.urlparse(url)
    parts = [p for p in u.path.split("/") if p and not re.fullmatch(r"[a-z]{2}-[A-Z]{2}", p)]
    tenant, site, out = u.netloc.split(".")[0], parts[0], []
    for off in range(0, 400, 20):
        r = requests.post(f"https://{u.netloc}/wday/cxs/{tenant}/{site}/jobs", headers=UA, timeout=30,
                          json={"limit": 20, "offset": off, "searchText": "", "appliedFacets": {}})
        r.raise_for_status()
        posts = r.json().get("jobPostings", [])
        out += [dict(title=p["title"], url=f"https://{u.netloc}/{site}{p['externalPath']}",
                     location=p.get("locationsText", ""), desc="") for p in posts]
        if len(posts) < 20: break
    return out


SKIP = re.compile(r"^(apply|careers?|jobs?|search|sign ?in|log ?in|home|about|contact|privacy|terms|cookie|learn more|view all|back)\b", re.I)
HINT = re.compile(r"job|career|position|opening|requisition|posting|vacanc|/o/|apply", re.I)


def generic(url):
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        b = p.chromium.launch()
        pg = b.new_page(user_agent=UA["User-Agent"])
        pg.goto(url, wait_until="networkidle", timeout=60000)
        pg.wait_for_timeout(2500)
        links = pg.eval_on_selector_all("a[href]", "els=>els.map(e=>[e.innerText.trim().split('\\n')[0],e.href])")
        b.close()
    seen, out = set(), []
    for t, h in links:
        if 6 <= len(t) <= 140 and not SKIP.match(t) and HINT.search(h) and h not in seen and h.rstrip("/") != url.rstrip("/"):
            seen.add(h); out.append(dict(title=t, url=h, location="", desc=""))
    return out


def fetch(url):
    u = up.urlparse(url); parts = [p for p in u.path.split("/") if p]
    if "greenhouse.io" in u.netloc and parts: return greenhouse(parts[0])
    if "lever.co" in u.netloc and parts: return lever(parts[0])
    if "myworkdayjobs.com" in u.netloc: return workday(url)
    return generic(url)


def main():
    sources = json.load(open("careers.json"))
    try: old = {j["id"]: j for j in json.load(open("jobs.json")).get("jobs", [])}
    except Exception: old = {}
    errors = {}
    for s in sources:
        url, name = s["url"], s.get("name") or up.urlparse(s["url"]).netloc
        try: found = fetch(url)
        except Exception as e:
            errors[url] = f"Fetch failed: {str(e)[:120]}"; continue
        if not found:
            errors[url] = "No jobs found. The page may block bots or need a custom rule."; continue
        ids = set()
        for f in found:
            i = jid(f["url"]); ids.add(i)
            j = old.get(i) or {"id": i, "first_seen": ISO}
            j.update(company=name, source=url, status="open", last_seen=ISO, title=f["title"], url=f["url"],
                     location=f.get("location", ""), desc=f.get("desc", "") or j.get("desc", ""))
            j.pop("closed_at", None); old[i] = j
        for j in old.values():
            if j["source"] == url and j["id"] not in ids and j["status"] == "open":
                j["status"], j["closed_at"] = "closed", ISO
    live = {s["url"] for s in sources}
    keep = [j for j in old.values() if j["source"] in live and not (
        j["status"] == "closed" and (NOW - dt.datetime.fromisoformat(j["closed_at"])).days > 14)]
    keep.sort(key=lambda j: j["first_seen"], reverse=True)
    json.dump({"updated": ISO, "errors": errors, "jobs": keep}, open("jobs.json", "w"), indent=1)
    print(f"{len(keep)} jobs, {len(errors)} errors")


if __name__ == "__main__":
    main()

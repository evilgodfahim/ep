#!/usr/bin/env python3
import sys
import os
from bs4 import BeautifulSoup
import xml.etree.ElementTree as ET
from xml.dom import minidom
from datetime import datetime, timezone, timedelta
from email.utils import parsedate_to_datetime
import json

# -----------------------------
# CONFIGURATION
# -----------------------------
HTML_FILE = "opinion.html"
XML_FILE = "articles.xml"
DAILY_FILE_PREFIX = "daily_feed"
LAST_SEEN_FILE = "last_seen.json"

MAX_ITEMS = 1000
MAX_ITEMS_PER_DAILY = 100
BD_OFFSET = 6
LOOKBACK_HOURS = 48
LINK_RETENTION_DAYS = 7

# -----------------------------
# DATE PARSER
# -----------------------------
def parse_date_from_text(date_text):
    if not date_text:
        return datetime.now(timezone.utc)

    # Try email/pubDate style format
    try:
        dt = parsedate_to_datetime(date_text)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:
        pass

    # Common formats
    formats = [
        "%b %d, %Y %I:%M %p",
        "%d %b %Y %H:%M:%S",
        "%Y-%m-%d %H:%M:%S",
    ]

    for fmt in formats:
        try:
            dt = datetime.strptime(date_text, fmt)
            return dt.replace(tzinfo=timezone.utc)
        except Exception:
            continue

    return datetime.now(timezone.utc)

# -----------------------------
# LOAD EXISTING XML ITEMS
# -----------------------------
def load_existing(file_path):
    if not os.path.exists(file_path):
        return []

    try:
        tree = ET.parse(file_path)
        root = tree.getroot()
    except Exception:
        return []

    items = []
    for item in root.findall(".//item"):
        try:
            title = (item.find("title").text or "").strip() if item.find("title") is not None else ""
            link = (item.find("link").text or "").strip() if item.find("link") is not None else ""
            desc = (item.find("description").text or "") if item.find("description") is not None else ""

            if item.find("pubDate") is not None and item.find("pubDate").text:
                pub = parse_date_from_text(item.find("pubDate").text)
            else:
                pub = datetime.now(timezone.utc)

            img = ""
            enc = item.find("enclosure")
            if enc is not None and enc.get("url"):
                img = enc.get("url")

            items.append({
                "title": title,
                "link": link,
                "description": desc,
                "pubDate": pub,
                "img": img
            })
        except Exception:
            continue

    return items

# -----------------------------
# WRITE RSS FILE
# -----------------------------
def write_rss(items, file_path, title="Feed"):
    rss = ET.Element("rss", version="2.0")
    channel = ET.SubElement(rss, "channel")

    ET.SubElement(channel, "title").text = title
    ET.SubElement(channel, "link").text = "https://www.newagebd.net"
    ET.SubElement(channel, "description").text = f"{title} - New Age BD"

    for item in items:
        node = ET.SubElement(channel, "item")

        ET.SubElement(node, "title").text = item.get("title", "")
        ET.SubElement(node, "link").text = item.get("link", "")
        ET.SubElement(node, "description").text = item.get("description", "")

        pub = item.get("pubDate")
        if isinstance(pub, datetime):
            ET.SubElement(node, "pubDate").text = pub.strftime("%a, %d %b %Y %H:%M:%S %z")
        else:
            ET.SubElement(node, "pubDate").text = str(pub)

        if item.get("img"):
            ET.SubElement(node, "enclosure", url=item["img"], type="image/jpeg")

    xml_str = minidom.parseString(ET.tostring(rss)).toprettyxml(indent="  ")

    with open(file_path, "w", encoding="utf-8") as f:
        f.write(xml_str)

# -----------------------------
# LAST SEEN
# -----------------------------
def load_last_seen():
    if not os.path.exists(LAST_SEEN_FILE):
        return {"last_seen": None}

    try:
        with open(LAST_SEEN_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            last_seen_str = data.get("last_seen")
            if last_seen_str:
                return {"last_seen": datetime.fromisoformat(last_seen_str)}
    except Exception:
        return {"last_seen": None}

    return {"last_seen": None}

def save_last_seen(last_dt):
    with open(LAST_SEEN_FILE, "w", encoding="utf-8") as f:
        json.dump({
            "last_seen": last_dt.isoformat(),
            "last_run": datetime.now(timezone.utc).isoformat()
        }, f, indent=2)

# -----------------------------
# SCRAPE HTML FILE
# -----------------------------
def scrape_articles():
    if not os.path.exists(HTML_FILE):
        print(f"HTML file '{HTML_FILE}' not found")
        return []

    with open(HTML_FILE, "r", encoding="utf-8") as f:
        soup = BeautifulSoup(f.read(), "html.parser")

    articles = []

    # Updated selector to match the HTML structure
    for card in soup.select("article.card.card-full.hover-a"):
        link_tag = card.select_one("h2.card-title a[href]")
        if not link_tag:
            continue

        url = link_tag.get("href", "")
        if not url:
            continue

        title = link_tag.get_text(strip=True)
        if not title:
            continue

        desc_tag = card.select_one("p.card-text")
        desc = desc_tag.get_text(strip=True) if desc_tag else ""

        time_tag = card.select_one("time")
        pub_text = time_tag.get_text(strip=True) if time_tag else ""
        pub_date = parse_date_from_text(pub_text)

        img_tag = card.select_one("img")
        img = ""
        if img_tag:
            img = img_tag.get("data-src", "") or img_tag.get("src", "")

        articles.append({
            "url": url,
            "title": title,
            "desc": desc,
            "pub": pub_date,
            "img": img
        })

    print(f"Found {len(articles)} articles in HTML")
    return articles

# -----------------------------
# UPDATE MAIN XML
# -----------------------------
def update_main_xml():
    print("[Updating articles.xml]")

    new_articles = scrape_articles()
    if not new_articles:
        print("No articles found")
        return

    # DEBUG: Print first few scraped articles
    print(f"\n📰 First 3 scraped articles:")
    for art in new_articles[:3]:
        print(f"  ✓ {art['title'][:60]}...")
        print(f"    URL: {art['url']}")
        print(f"    Date: {art['pub']}")

    # Load or create root
    if os.path.exists(XML_FILE):
        try:
            tree = ET.parse(XML_FILE)
            root = tree.getroot()
            print(f"\n✓ Loaded existing {XML_FILE}")
        except ET.ParseError:
            print(f"\n⚠ Could not parse {XML_FILE}, creating new file")
            root = ET.Element("rss", version="2.0")
    else:
        print(f"\n⚠ {XML_FILE} does not exist, creating new file")
        root = ET.Element("rss", version="2.0")

    channel = root.find("channel")
    if channel is None:
        channel = ET.SubElement(root, "channel")
        ET.SubElement(channel, "title").text = "New Age BD News"
        ET.SubElement(channel, "link").text = "https://www.newagebd.net"
        ET.SubElement(channel, "description").text = "Latest news articles"

    existing_links = set()
    for item in channel.findall("item"):
        lk = item.find("link")
        if lk is not None and lk.text:
            existing_links.add(lk.text.strip())

    # DEBUG: Show how many existing links
    print(f"\n📋 Existing links in XML: {len(existing_links)}")

    new_nodes = []
    new_count = 0
    skipped_count = 0

    for art in new_articles:
        if art["url"] in existing_links:
            skipped_count += 1
            continue

        node = ET.Element("item")
        ET.SubElement(node, "title").text = art["title"]
        ET.SubElement(node, "link").text = art["url"]
        ET.SubElement(node, "description").text = art["desc"]
        ET.SubElement(node, "pubDate").text = art["pub"].strftime("%a, %d %b %Y %H:%M:%S %z")

        if art["img"]:
            ET.SubElement(node, "enclosure", url=art["img"], type="image/jpeg")

        new_nodes.append(node)
        existing_links.add(art["url"])
        new_count += 1

    print(f"\n➕ Added {new_count} new articles")
    print(f"⏭  Skipped {skipped_count} duplicate articles")

    # Insert at top
    insert_pos = 0
    for child in channel:
        if child.tag in ["title", "link", "description"]:
            insert_pos += 1
        else:
            break

    for i, nd in enumerate(new_nodes):
        channel.insert(insert_pos + i, nd)

    # Trim
    all_items = channel.findall("item")
    if len(all_items) > MAX_ITEMS:
        to_remove = len(all_items) - MAX_ITEMS
        for old in all_items[-to_remove:]:
            channel.remove(old)
        print(f"✂️  Removed {to_remove} old articles (keeping {MAX_ITEMS} max)")

    # Save XML
    tree = ET.ElementTree(root)
    ET.indent(tree, space="  ", level=0)
    tree.write(XML_FILE, encoding="utf-8", xml_declaration=True)

    print(f"✓ Saved {XML_FILE}")

# -----------------------------
# UPDATE DAILY FEED
# -----------------------------
def update_daily():
    print("\n[Updating daily feed]")

    last = load_last_seen()
    last_seen_dt = last["last_seen"]

    if last_seen_dt:
        cutoff = last_seen_dt
        print(f"Using last seen cutoff: {cutoff}")
    else:
        cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
        print(f"No last seen, using 24h cutoff: {cutoff}")

    master = load_existing(XML_FILE)
    print(f"Loaded {len(master)} articles from {XML_FILE}")

    fresh = []
    seen = set()

    for item in master:
        link = item["link"]
        pub = item["pubDate"]

        if link in seen:
            continue

        if pub > cutoff:
            fresh.append(item)
            seen.add(link)

    print(f"Found {len(fresh)} fresh articles since cutoff")

    if not fresh:
        placeholder = [{
            "title": "No new articles",
            "link": "https://www.newagebd.net",
            "description": "No new entries.",
            "pubDate": datetime.now(timezone.utc),
            "img": ""
        }]

        write_rss(placeholder, f"{DAILY_FILE_PREFIX}.xml", title="Daily Feed")
        save_last_seen(datetime.now(timezone.utc))
        print("✓ No new articles. Placeholder written.")
        return [f"{DAILY_FILE_PREFIX}.xml"]

    fresh.sort(key=lambda x: x["pubDate"], reverse=True)

    batches = []
    for i in range(0, len(fresh), MAX_ITEMS_PER_DAILY):
        batches.append(fresh[i:i + MAX_ITEMS_PER_DAILY])

    created = []

    for idx, batch in enumerate(batches):
        if idx == 0:
            fname = f"{DAILY_FILE_PREFIX}.xml"
            title = "Daily Feed"
        else:
            fname = f"{DAILY_FILE_PREFIX}_{idx+1}.xml"
            title = f"Daily Feed {idx+1}"

        write_rss(batch, fname, title)
        created.append(fname)
        print(f"✓ Saved {fname} with {len(batch)} articles")

    last_dt = max(i["pubDate"] for i in fresh)
    save_last_seen(last_dt)

    print(f"✓ Updated last seen to {last_dt}")

    return created

# -----------------------------
# MAIN
# -----------------------------
if __name__ == "__main__":
    args = sys.argv[1:]

    print("=" * 60)
    print("New Age BD Article Scraper")
    print("=" * 60)

    files_created = []

    if "--daily-only" in args:
        daily_files = update_daily()
        files_created = daily_files + [LAST_SEEN_FILE]

    elif "--main-only" in args:
        update_main_xml()
        files_created = [XML_FILE]

    else:
        update_main_xml()
        daily_files = update_daily()
        files_created = [XML_FILE] + daily_files + [LAST_SEEN_FILE]

    print("\n" + "=" * 60)
    print("FILES CREATED/UPDATED:")
    print("=" * 60)

    for f in files_created:
        exists = "✓ EXISTS" if os.path.exists(f) else "✗ NOT FOUND"
        size = os.path.getsize(f) if os.path.exists(f) else 0
        print(f"{exists} | {f} ({size} bytes)")

    print("\n✓ All operations completed!")
    print("=" * 60)
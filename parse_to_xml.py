import sys
import os
from bs4 import BeautifulSoup
import xml.etree.ElementTree as ET
from xml.dom import minidom
from datetime import datetime, timezone, timedelta
from email.utils import parsedate_to_datetime
import json

HTML_FILE = "news.html"
XML_FILE = "articles.xml"
DAILY_FILE = "daily_feed.xml"
DAILY_FILE_2 = "daily_feed_2.xml"
LAST_SEEN_FILE = "last_seen.json"

MAX_ITEMS = 1000
BD_OFFSET = 6
LOOKBACK_HOURS = 48
LINK_RETENTION_DAYS = 7

# -----------------------------
# UTILITIES
# -----------------------------
def parse_date_from_text(date_text):
    """Parse date from various formats"""
    if not date_text:
        return datetime.now(timezone.utc)
    
    try:
        # Try email format first
        dt = parsedate_to_datetime(date_text)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:
        pass
    
    # Try common formats
    formats = [
        "%b %d, %Y %I:%M %p",  # Dec 12, 2025 01:27 PM
        "%d %b %Y %H:%M:%S",   # 12 Dec 2025 01:27:00
        "%Y-%m-%d %H:%M:%S",   # 2025-12-12 01:27:00
    ]
    
    for fmt in formats:
        try:
            dt = datetime.strptime(date_text, fmt)
            return dt.replace(tzinfo=timezone.utc)
        except Exception:
            continue
    
    return datetime.now(timezone.utc)

def load_existing(file_path):
    """Load existing items from XML file"""
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
            title_node = item.find("title")
            link_node = item.find("link")
            desc_node = item.find("description")
            pub_node = item.find("pubDate")
            
            title = (title_node.text or "").strip() if title_node is not None else ""
            link = (link_node.text or "").strip() if link_node is not None else ""
            desc = desc_node.text or "" if desc_node is not None else ""
            
            if pub_node is not None and pub_node.text:
                dt = parse_date_from_text(pub_node.text)
            else:
                dt = datetime.now(timezone.utc)
            
            items.append({
                "title": title,
                "link": link,
                "description": desc,
                "pubDate": dt,
                "img": item.find("enclosure").get("url", "") if item.find("enclosure") is not None else ""
            })
        except Exception:
            continue
    return items

def write_rss(items, file_path, title="Feed"):
    """Write items to RSS XML file"""
    rss = ET.Element("rss", version="2.0")
    channel = ET.SubElement(rss, "channel")
    ET.SubElement(channel, "title").text = title
    ET.SubElement(channel, "link").text = "https://www.newagebd.net"
    ET.SubElement(channel, "description").text = f"{title} - New Age BD News"

    for item in items:
        it = ET.SubElement(channel, "item")
        ET.SubElement(it, "title").text = item.get("title", "")
        ET.SubElement(it, "link").text = item.get("link", "")
        ET.SubElement(it, "description").text = item.get("description", "")
        
        pub = item.get("pubDate")
        if isinstance(pub, datetime):
            ET.SubElement(it, "pubDate").text = pub.strftime("%a, %d %b %Y %H:%M:%S %z")
        else:
            ET.SubElement(it, "pubDate").text = str(pub)
        
        if item.get("img"):
            ET.SubElement(it, "enclosure", url=item["img"], type="image/jpeg")

    xml_str = minidom.parseString(ET.tostring(rss)).toprettyxml(indent="  ")
    with open(file_path, "w", encoding="utf-8") as f:
        f.write(xml_str)

# -----------------------------
# LAST SEEN TRACKING
# -----------------------------
def load_last_seen():
    """Load last seen timestamp and processed links"""
    if os.path.exists(LAST_SEEN_FILE):
        try:
            with open(LAST_SEEN_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                last_seen_str = data.get("last_seen")
                processed = set(data.get("processed_links", []))
                last_seen_dt = datetime.fromisoformat(last_seen_str) if last_seen_str else None
                return {"last_seen": last_seen_dt, "processed_links": processed}
        except Exception:
            return {"last_seen": None, "processed_links": set()}
    return {"last_seen": None, "processed_links": set()}

def save_last_seen(last_dt, processed_links, master_items):
    """Save last seen timestamp and clean up old processed links"""
    cutoff = last_dt - timedelta(days=LINK_RETENTION_DAYS)
    master_links_recent = {
        item["link"] for item in master_items
        if item["pubDate"] > cutoff
    }
    links_to_keep = [link for link in processed_links if link in master_links_recent]

    with open(LAST_SEEN_FILE, "w", encoding="utf-8") as f:
        json.dump({
            "last_seen": last_dt.isoformat(),
            "processed_links": links_to_keep
        }, f, indent=2)

# -----------------------------
# SCRAPE ARTICLES FROM HTML
# -----------------------------
def scrape_articles():
    """Extract articles from New Age BD HTML"""
    # Load HTML
    if not os.path.exists(HTML_FILE):
        print(f"HTML file '{HTML_FILE}' not found")
        return []

    with open(HTML_FILE, "r", encoding="utf-8") as f:
        soup = BeautifulSoup(f.read(), "html.parser")

    articles = []

    # Extract articles from New Age BD format
    for article_card in soup.select("article.card.card-full.hover-a"):
        link_tag = article_card.select_one("a[href]")
        if not link_tag:
            continue
        
        url = link_tag.get("href", "")
        if not url:
            continue
        
        # Get title
        title_tag = article_card.select_one("h2.card-title a")
        title = title_tag.get_text(strip=True) if title_tag else None
        if not title:
            continue
        
        # Get description
        desc_tag = article_card.select_one("p.card-text")
        desc = desc_tag.get_text(strip=True) if desc_tag else ""
        
        # Get publication date
        time_tag = article_card.select_one("time")
        pub_text = time_tag.get_text(strip=True) if time_tag else ""
        pub_date = parse_date_from_text(pub_text)
        
        # Get image
        img_tag = article_card.select_one("img")
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
# UPDATE MAIN XML FILE
# -----------------------------
def update_main_xml():
    """Update the main articles.xml file"""
    print("[Updating articles.xml]")
    
    articles = scrape_articles()
    if not articles:
        print("No articles found in HTML")
        return
    
    # Load existing XML
    if os.path.exists(XML_FILE):
        try:
            tree = ET.parse(XML_FILE)
            root = tree.getroot()
        except ET.ParseError:
            root = ET.Element("rss", version="2.0")
    else:
        root = ET.Element("rss", version="2.0")

    # Ensure channel exists
    channel = root.find("channel")
    if channel is None:
        channel = ET.SubElement(root, "channel")
        ET.SubElement(channel, "title").text = "New Age BD News"
        ET.SubElement(channel, "link").text = "https://www.newagebd.net"
        ET.SubElement(channel, "description").text = "Latest news articles from New Age Bangladesh"

    # Deduplicate existing URLs
    existing = set()
    for item in channel.findall("item"):
        link_tag = item.find("link")
        if link_tag is not None:
            existing.add(link_tag.text.strip())

    # Create new items for unique articles
    new_items = []
    new_count = 0
    for art in articles:
        if art["url"] in existing:
            continue
        
        item = ET.Element("item")
        ET.SubElement(item, "title").text = art["title"]
        ET.SubElement(item, "link").text = art["url"]
        ET.SubElement(item, "description").text = art["desc"]
        ET.SubElement(item, "pubDate").text = art["pub"].strftime("%a, %d %b %Y %H:%M:%S %z")
        
        if art["img"]:
            ET.SubElement(item, "enclosure", url=art["img"], type="image/jpeg")
        
        existing.add(art["url"])
        new_items.append(item)
        new_count += 1

    # Insert new items at the top of the channel
    insert_position = 0
    for child in channel:
        if child.tag in ["title", "link", "description"]:
            insert_position += 1
        else:
            break

    for i, item in enumerate(new_items):
        channel.insert(insert_position + i, item)

    print(f"Added {new_count} new articles at the top")

    # Trim to last MAX_ITEMS
    all_items = channel.findall("item")
    if len(all_items) > MAX_ITEMS:
        removed = len(all_items) - MAX_ITEMS
        for old_item in all_items[:-MAX_ITEMS]:
            channel.remove(old_item)
        print(f"Removed {removed} old articles (keeping last {MAX_ITEMS})")

    # Save XML with proper formatting
    tree = ET.ElementTree(root)
    ET.indent(tree, space="  ", level=0)
    tree.write(XML_FILE, encoding="utf-8", xml_declaration=True)

    print(f"✓ {XML_FILE} updated")
    print(f"Total articles in feed: {len(channel.findall('item'))}")

# -----------------------------
# UPDATE DAILY FEED
# -----------------------------
def update_daily():
    """Update daily feed with new articles since last run"""
    print("\n[Updating daily_feed.xml with robust tracking]")
    to_zone = timezone(timedelta(hours=BD_OFFSET))

    last_data = load_last_seen()
    last_seen_dt = last_data["last_seen"]
    processed_links = set(last_data["processed_links"])

    if last_seen_dt:
        lookback_dt = last_seen_dt - timedelta(hours=LOOKBACK_HOURS)
    else:
        lookback_dt = None

    master_items = load_existing(XML_FILE)
    new_items = []

    for item in master_items:
        link = item["link"]
        pub = item["pubDate"].astimezone(to_zone)

        if link in processed_links:
            continue

        if not lookback_dt or pub > lookback_dt:
            new_items.append(item)
            processed_links.add(link)

    if not new_items:
        placeholder = [{
            "title": "No new articles today",
            "link": "https://www.newagebd.net",
            "description": "Daily feed will populate after first articles appear.",
            "pubDate": datetime.now(timezone.utc),
            "img": ""
        }]

        write_rss(placeholder, DAILY_FILE, title="Daily Feed - New Age BD")
        write_rss([], DAILY_FILE_2, title="Daily Feed Extra - New Age BD")

        last_dt = placeholder[0]["pubDate"]
        save_last_seen(last_dt, processed_links, master_items)
        print("✓ No new articles for daily feed")
        return

    new_items.sort(key=lambda x: x["pubDate"], reverse=True)

    first_batch = new_items[:100]
    second_batch = new_items[100:]

    write_rss(first_batch, DAILY_FILE, title="Daily Feed - New Age BD")
    print(f"✓ {DAILY_FILE} created with {len(first_batch)} articles")

    if second_batch:
        write_rss(second_batch, DAILY_FILE_2, title="Daily Feed Extra - New Age BD")
        print(f"✓ {DAILY_FILE_2} created with {len(second_batch)} articles")
    else:
        write_rss([], DAILY_FILE_2, title="Daily Feed Extra - New Age BD")
        print(f"✓ {DAILY_FILE_2} created (empty)")

    last_dt = max([i["pubDate"] for i in new_items])
    save_last_seen(last_dt, processed_links, master_items)
    print(f"✓ Processed {len(new_items)} new articles for daily feed")

# -----------------------------
# MAIN
# -----------------------------
if __name__ == "__main__":
    args = sys.argv[1:]
    
    if "--daily-only" in args:
        update_daily()
    elif "--main-only" in args:
        update_main_xml()
    else:
        # Default: update both
        update_main_xml()
        update_daily()
    
    print("\n✓ All operations completed!")

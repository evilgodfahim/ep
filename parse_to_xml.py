import sys
import os
from bs4 import BeautifulSoup
import xml.etree.ElementTree as ET
from datetime import datetime

HTML_FILE = "news.html"
XML_FILE = "articles.xml"
MAX_ITEMS = 1000

# Load HTML
if not os.path.exists(HTML_FILE):
    print("HTML not found")
    sys.exit(1)

with open(HTML_FILE, "r", encoding="utf-8") as f:
    soup = BeautifulSoup(f.read(), "html.parser")

articles = []

# Extract articles from New Age BD format
# Looking for article cards with class "card card-full hover-a"
for article_card in soup.select("article.card.card-full.hover-a"):
    # Find the link
    link_tag = article_card.select_one("a[href]")
    if not link_tag:
        continue
    
    url = link_tag.get("href", "")
    if not url:
        continue
    
    # Get title from h2 > a
    title_tag = article_card.select_one("h2.card-title a")
    title = title_tag.get_text(strip=True) if title_tag else None
    if not title:
        continue
    
    # Get description from card-text paragraph
    desc_tag = article_card.select_one("p.card-text")
    desc = desc_tag.get_text(strip=True) if desc_tag else ""
    
    # Get publication date from time tag
    time_tag = article_card.select_one("time")
    pub = time_tag.get_text(strip=True) if time_tag else ""
    
    # Get image from img tag
    img_tag = article_card.select_one("img")
    img = ""
    if img_tag:
        # Try data-src first (lazy loading), then src
        img = img_tag.get("data-src", "") or img_tag.get("src", "")
    
    articles.append({
        "url": url,
        "title": title,
        "desc": desc,
        "pub": pub,
        "img": img
    })

print(f"Found {len(articles)} articles")

# Load or create XML
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
    
    # Use article's publication date if available, else current time
    if art["pub"]:
        ET.SubElement(item, "pubDate").text = art["pub"]
    else:
        ET.SubElement(item, "pubDate").text = datetime.utcnow().strftime("%a, %d %b %Y %H:%M:%S +0000")
    
    if art["img"]:
        ET.SubElement(item, "enclosure", url=art["img"], type="image/jpeg")
    
    existing.add(art["url"])
    new_items.append(item)
    new_count += 1

# Insert new items at the top of the channel (after title, link, description)
# Find the position after channel metadata
insert_position = 0
for child in channel:
    if child.tag in ["title", "link", "description"]:
        insert_position += 1
    else:
        break

# Insert new items at the top
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

print(f"RSS feed saved to {XML_FILE}")
print(f"Total articles in feed: {len(channel.findall('item'))}")

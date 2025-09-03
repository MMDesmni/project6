#Importing libraries that we need

from __future__ import annotations
import re
import time
import csv
import sys
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import List, Set, Optional

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException

#Config

BASE_URL = "https://akharinkhabar.ir"
CATEGORY_PATHS = {
    "sport": "/sport",
    "politics": "/politics",
    "money": "/money",         
    "world": "/world",          
    "social": "/social",        
}
TARGET_PER_CATEGORY = 200
MAX_SCROLLS_PER_CATEGORY = 1000  
SCROLL_PAUSE_SEC = 1.0
PAGE_LOAD_TIMEOUT = 20
WAIT_TIMEOUT = 15
OUT_CSV = Path("akharinkhabar_news.csv")

#Util

ZERO_WIDTH = "\u200c\u200f\u202a\u202b\u202c\u202d\u202e\ufeff"
ZW_RE = re.compile(f"[{ZERO_WIDTH}]")
WS_RE = re.compile(r"\s+")
BLOCKLIST_SNIPPETS = [
    "ما را در کانال تلگرامی",
    "بازار",
    "* * *",
]

#Creating the standard version for date time

TIME_RE = re.compile(r"(\d{4}/\d{2}/\d{2})\s*-\s*(\d{2}:\d{2})")  

#Class for extracting the important datas

@dataclass
class NewsItem:
    category: str
    title: str
    url: str
    image_url: str
    publish_datetime: str
    text: str

#This function just normalize texts

def normalize_text(s: str) -> str:
    if not s:
        return ""
    s = ZW_RE.sub("", s)
    s = s.replace("\r", " ").replace("\n", " ")
    s = WS_RE.sub(" ", s).strip()
    return s

#Cleaning data before adding it to files

def clean_paragraphs(paragraphs: List[str]) -> str:
    cleaned = []
    for p in paragraphs:
        p = normalize_text(p)
        if not p:
            continue
        if any(snip in p for snip in BLOCKLIST_SNIPPETS):
            continue
        if len(p) < 2:
            continue
        cleaned.append(p)
    seen = set()
    uniq = []
    for p in cleaned:
        if p not in seen:
            seen.add(p)
            uniq.append(p)
    return "\n".join(uniq)


#Selenium setup

def make_driver(headless: bool = True) -> webdriver.Chrome:
    opts = Options()
    if headless:
        opts.add_argument("--headless=new")
    opts.add_argument("--disable-gpu")
    opts.add_argument("--no-sandbox")
    opts.add_argument("--window-size=1440,2000")
    opts.add_argument("--lang=fa-IR")
    opts.add_argument("--disable-dev-shm-usage")
    opts.add_argument("--blink-settings=imagesEnabled=true")
    opts.add_argument(
        "--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
    )
    driver = webdriver.Chrome(options=opts)
    driver.set_page_load_timeout(PAGE_LOAD_TIMEOUT)
    return driver


#For getting every list that we could(clicking the more news button)

def infinite_scroll_collect_links(driver: webdriver.Chrome, category_key: str, target_count: int) -> List[str]:
    url = BASE_URL + CATEGORY_PATHS[category_key]
    driver.get(url)
    wait = WebDriverWait(driver, WAIT_TIMEOUT)

    #Waiting for آخرین خبر ها to appear and after that we do our job

    try:
        wait.until(EC.presence_of_element_located((By.XPATH, "//h3[contains(., 'آخرین خبرها')]")))
    except TimeoutException:
        print(f"[WARN] 'آخرین خبرها' not found for {category_key}, continuing anyway…", file=sys.stderr)

    links: Set[str] = set()
    last_height = 0

    for i in range(MAX_SCROLLS_PER_CATEGORY):
        anchors = driver.find_elements(By.XPATH,
            (
                "//a[contains(@href, '{}{}/') and not(contains(@href,'/video/'))]"
            ).format(BASE_URL, CATEGORY_PATHS[category_key])
        )
        for a in anchors:
            href = a.get_attribute("href")
            if href and re.search(r"/\d{6,}/", href):
                links.add(href)
        if len(links) >= target_count:
            break
        driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
        time.sleep(SCROLL_PAUSE_SEC)

        #Basiclly this part is where that we see that there is no more news and as they say the page is stuck

        new_height = driver.execute_script("return document.body.scrollHeight")
        if new_height == last_height:
            driver.execute_script("window.scrollTo(0, Math.max(0, document.body.scrollHeight-1200));")
            time.sleep(0.5)
            driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
            time.sleep(0.5)
            newer_height = driver.execute_script("return document.body.scrollHeight")
            if newer_height == last_height:
                print(f"[INFO] Reached end on {category_key} after {i} scrolls with {len(links)} links.")
                break
            last_height = newer_height
        else:
            last_height = new_height

    ordered = list(links)[:target_count]
    return ordered


#This part scraps the article itself

def extract_article(driver: webdriver.Chrome, url: str, category_key: str) -> Optional[NewsItem]:
    try:
        driver.get(url)
    except Exception as e:
        print(f"[ERROR] Navigation failed: {url} :: {e}")
        return None

    wait = WebDriverWait(driver, WAIT_TIMEOUT)

    title = ""
    try:
        title_el = wait.until(EC.presence_of_element_located((By.XPATH, "//h1 | //h1/*[self::span or self::strong]/..")))
        title = normalize_text(title_el.text)
    except TimeoutException:
        try:
            title_el = driver.find_element(By.XPATH, "//*[contains(@class,'title')][1]")
            title = normalize_text(title_el.text)
        except NoSuchElementException:
            title = ""
    publish_dt = ""
    try:
        meta_el = driver.find_element(By.XPATH, "//*[contains(., 'بروزرسانی') and (self::div or self::span or self::p)]")
        meta_text = normalize_text(meta_el.text)
        m = TIME_RE.search(meta_text)
        if m:
            publish_dt = f"{m.group(1)} {m.group(2)}"
        else:
            #Turning the time date to normal time date
            body_text = normalize_text(driver.find_element(By.TAG_NAME, "body").text)
            m2 = TIME_RE.search(body_text)
            if m2:
                publish_dt = f"{m2.group(1)} {m2.group(2)}"
    except NoSuchElementException:
        pass

    image_url = ""
    try:
        img_candidates = driver.find_elements(By.XPATH, "//img[not(ancestor::header)]")
        for img in img_candidates[:10]:
            src = img.get_attribute("src") or img.get_attribute("data-src") or ""
            if src and "/images/" in src:
                image_url = src
                break
    except Exception:
        pass

    paragraphs: List[str] = []
    xpaths = [
        "//div[contains(@class,'content') or contains(@class,'article') or contains(@class,'post')][1]//p",
        "//article//p",
        "//div[contains(@id,'content')][1]//p",
    ]
    for xp in xpaths:

        # A simple try that sees that they are any image near the paragraph

        try:
            elems = driver.find_elements(By.XPATH, xp)
            if elems:
                paragraphs = [e.text for e in elems]
                break
        except Exception:
            continue
    if not paragraphs:
        try:
            blob = driver.find_element(By.TAG_NAME, "body").text
            paragraphs = [p.strip() for p in blob.split("\n") if p.strip()]
        except Exception:
            paragraphs = []

    text = clean_paragraphs(paragraphs)

    return NewsItem(
        category=category_key,
        title=title,
        url=url,
        image_url=image_url,
        publish_datetime=publish_dt,
        text=text,
    )


#This function just concludes all of the last functions

def main(headless: bool = True):
    driver = make_driver(headless=headless)
    all_items: List[NewsItem] = []
    try:
        for cat in CATEGORY_PATHS.keys():
            #print(f"[INFO] Category: {cat}")
            links = infinite_scroll_collect_links(driver, cat, TARGET_PER_CATEGORY)
            #print(f"[INFO] Collected {len(links)} links for {cat}")
            count = 0
            for href in links:
                item = extract_article(driver, href, cat)
                if item is None:
                    continue
                item.title = normalize_text(item.title)
                item.text = normalize_text(item.text)
                item.image_url = (item.image_url or "").strip()
                item.publish_datetime = (item.publish_datetime or "").strip()
                if not item.title or not item.text:
                    continue
                all_items.append(item)
                count += 1
                if count % 10 == 0:
                    print(f"  scraped {count}/{TARGET_PER_CATEGORY} for {cat}…")
            print(f"[DONE] {cat}: {count} items scraped.")
    finally:
        driver.quit()

    #Save file as csv

    OUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    with OUT_CSV.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=[
            "category", "title", "url", "image_url", "publish_datetime", "text"
        ])
        writer.writeheader()
        for item in all_items:
            writer.writerow(asdict(item))

    print(f"Saved {len(all_items)} rows to {OUT_CSV.resolve()}")

if __name__ == "__main__":
    main(headless=True)
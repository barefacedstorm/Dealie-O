import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin
import tkinter as tk
from tkinter import ttk, messagebox
import re
from datetime import datetime
import ssl
from concurrent.futures import ThreadPoolExecutor
import csv
import warnings

# Suppress SSL warnings
warnings.filterwarnings('ignore', category=requests.packages.urllib3.exceptions.InsecureRequestWarning)
ssl._create_default_https_context = ssl._create_unverified_context


def safe_request(url, max_retries=3):
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
        'Accept-Language': 'en-US,en;q=0.9',
    }

    for _ in range(max_retries):
        try:
            response = requests.get(url, headers=headers, timeout=15, verify=False)
            response.raise_for_status()
            return response
        except Exception as e:
            continue
    return None


def extract_promotions(soup, base_url):
    promotions = []
    price_pattern = re.compile(
        r'\$[\d,]+(?:\.\d{2})?|'  # Standard prices ($10.99)
        r'\$\d+-\d+|'  # Price ranges ($5-$10)
        r'\d+\s*%|'  # Percent discounts
        r'(?:save|off)\s+\$?\d+',  # Save offers
        re.IGNORECASE
    )

    selectors = [
        ('div', {'class': re.compile(r'promo|deal|offer|special|banner|price', re.I)}),
        ('section', {'id': re.compile(r'specials|offers|deals|price', re.I)}),
        ('li', {'class': re.compile(r'menu-item|product|item|price', re.I)}),
        ('article', {'class': re.compile(r'card|offer|promotion|price', re.I)}),
        ('tr', {'class': re.compile(r'deal|offer|price', re.I)}),
        ('a', {'href': re.compile(r'/deals|/offers|/promotions|/price', re.I)})
    ]

    for tag, attrs in selectors:
        for element in soup.find_all(tag, attrs):
            try:
                # Extract title with improved filtering
                title_element = element.find(['h1', 'h2', 'h3', 'h4', 'span', 'div'],
                                             class_=re.compile(r'title|heading|name', re.I))
                title = title_element.get_text(strip=True) if title_element else ""

                # Skip generic/unhelpful titles
                if not title or re.search(r'undefined|promo|deal|offer', title, re.I):
                    title = ""

                # Price detection in multiple locations
                price = ""
                for el in [element] + element.find_all(['span', 'div']):
                    price_match = price_pattern.search(el.get_text())
                    if price_match and not price:
                        price = price_match.group().strip()
                        break

                # Description extraction
                description = ""
                for desc_el in element.find_all(['p', 'div']):
                    text = desc_el.get_text(strip=True)
                    if text and not re.search(r'undefined|promo|deal|offer', text, re.I):
                        description = text
                        break

                # Image detection
                img_element = element.find('img')
                image = ""
                if img_element:
                    for attr in ['src', 'data-src', 'data-original']:
                        if img_element.has_attr(attr):
                            image = img_element[attr]
                            if not image.startswith(('http', '//')):
                                image = urljoin(base_url, image)
                            break

                # Only add entries with valid pricing information
                if price or (title and description):
                    promotions.append({
                        'title': title,
                        'description': description,
                        'price': price,
                        'image': image,
                        'date': datetime.now().strftime('%Y-%m-%d'),
                        'source': base_url
                    })
            except Exception as e:
                continue

    return promotions


def scrape_competitor_data(url, max_depth=1):
    results = []
    visited = set()

    def recursive_scrape(current_url, depth):
        if depth > max_depth or current_url in visited:
            return
        visited.add(current_url)

        response = safe_request(current_url)
        if not response:
            return

        soup = BeautifulSoup(response.content, 'html.parser')
        promotions = extract_promotions(soup, current_url)

        # Filter out low-quality entries
        filtered_promotions = [
            p for p in promotions
            if p['price'] or (p['title'] and p['description'])
        ]

        results.extend(filtered_promotions)

        if depth < max_depth:
            for link in soup.find_all('a', href=True):
                absolute_url = urljoin(current_url, link['href'])
                if absolute_url not in visited and absolute_url.startswith(url):
                    recursive_scrape(absolute_url, depth + 1)

    try:
        recursive_scrape(url, 0)
    except Exception as e:
        pass

    return results


class CompetitorTrackerApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Dealie-O")
        self.root.geometry("1200x800")
        self.results = []
        self.create_widgets()
        self.executor = ThreadPoolExecutor(max_workers=5)

    def create_widgets(self):
        main_frame = ttk.Frame(self.root)
        main_frame.pack(fill=tk.BOTH, expand=True, padx=20, pady=20)

        # Input Section
        input_frame = ttk.Frame(main_frame)
        input_frame.pack(fill=tk.X, pady=10)

        self.url_entry = ttk.Entry(input_frame, width=60)
        self.url_entry.pack(side=tk.LEFT, padx=5)
        self.url_entry.insert(0, "https://www.example.com/")

        ttk.Button(input_frame, text="Search", command=self.start_scraping).pack(side=tk.LEFT, padx=5)
        ttk.Button(input_frame, text="Export to CSV", command=self.export_csv).pack(side=tk.LEFT, padx=5)

        # Results Display
        self.tree = ttk.Treeview(main_frame, columns=('Price', 'Source', 'Description', 'Title'), show='headings')
        self.tree.heading('Price', text='Price', anchor=tk.W)
        self.tree.heading('Description', text='Description', anchor=tk.W)
        self.tree.heading('Source', text='Source', anchor=tk.W)
        self.tree.heading('Title', text='Link', anchor=tk.W)


        self.tree.column('Price', width=80, anchor=tk.W)
        self.tree.column('Description', width=400, anchor=tk.W)
        self.tree.column('Source', width=200, anchor=tk.W)
        self.tree.column('Title', width=250, anchor=tk.W)


        self.tree.pack(fill=tk.BOTH, expand=True, pady=10)

        # Status Bar
        self.status = ttk.Label(self.root, text="Ready", anchor=tk.W)
        self.status.pack(side=tk.BOTTOM, fill=tk.X)

    def start_scraping(self):
        url = self.url_entry.get().strip()
        if not url.startswith('http'):
            messagebox.showwarning("Input Error", "Please enter a valid URL starting with http:// or https://")
            return

        self.status.config(text="Search in progress...")
        self.tree.delete(*self.tree.get_children())
        self.executor.submit(self.perform_scraping, url)

    def perform_scraping(self, url):
        try:
            results = scrape_competitor_data(url, max_depth=2)
            self.results = results
            self.root.after(0, self.update_results, results)
            self.root.after(0, lambda: self.status.config(text=f"Found {len(results)} valid promotions"))
        except Exception as e:
            self.root.after(0, lambda: messagebox.showerror("Error", str(e)))
            self.root.after(0, lambda: self.status.config(text="Error occurred"))

    def update_results(self, results):
        for promo in results:
            self.tree.insert('', tk.END, values=(
                promo['price'],
                promo['title'],
                promo['description'],
                promo['source']
            ))

    def export_csv(self):
        if not self.results:
            messagebox.showwarning("No Data", "No data to export")
            return

        with open('promotions.csv', 'w', newline='', encoding='utf-8') as f:
            writer = csv.DictWriter(f, fieldnames=['title', 'description', 'price', 'date', 'source', 'image'])
            writer.writeheader()
            writer.writerows(self.results)
        messagebox.showinfo("Export Complete", "Data exported to promotions.csv")


if __name__ == "__main__":
    root = tk.Tk()
    app = CompetitorTrackerApp(root)
    root.mainloop()

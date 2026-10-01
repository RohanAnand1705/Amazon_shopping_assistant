import asyncio
import re
import tkinter as tk
from tkinter import messagebox
from urllib.parse import quote_plus

import httpx
from bs4 import BeautifulSoup
from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeoutError


HTTP_CONCURRENT_CHECKS = 10
FALLBACK_CONCURRENT_CHECKS = 2
HTTP_TIMEOUT = 12

HIGHLIGHT_BORDER = "4px solid green"
HIGHLIGHT_BACKGROUND = "#d4ffd4"
HIGHLIGHT_SHADOW = "0 0 10px green"


def clean_text(value):
    if value is None:
        return ""
    return re.sub(r"\s+", " ", str(value)).strip()


def normalize_size(value):
    value = clean_text(value).lower()
    value = re.sub(r"\s+", "", value)
    value = re.sub(r"[^a-z0-9.+-]", "", value)
    return value


def parse_price(value):
    if value is None:
        return None

    text = str(value).replace(",", "")
    match = re.search(r"(?:₹|rs\.?\s*)?([0-9]+(?:\.[0-9]+)?)", text, re.IGNORECASE)
    if not match:
        return None

    try:
        return int(float(match.group(1)))
    except (TypeError, ValueError):
        return None


def price_matches(actual_price, minimum_price, maximum_price):
    if actual_price is None:
        return False if (minimum_price or maximum_price) else True

    if minimum_price and actual_price < int(minimum_price):
        return False

    if maximum_price and actual_price > int(maximum_price):
        return False

    return True


def material_matches(actual_material, required_material):
    required = clean_text(required_material).lower()

    if not required:
        return True

    if not actual_material:
        return False

    actual = clean_text(actual_material).lower()

    alternatives = re.split(
        r"\s*(?:/|\bor\b|\|)\s*",
        required,
        flags=re.IGNORECASE,
    )

    for option in alternatives:
        option = option.strip()
        if not option:
            continue

        percentage_match = re.search(r"(\d+)\s*%", option)

        if percentage_match:
            required_percent = percentage_match.group(1)

            actual_percent_match = re.search(r"(\d+)\s*%", actual)
            if not actual_percent_match:
                continue

            actual_percent = actual_percent_match.group(1)
            if actual_percent != required_percent:
                continue

            material_part = re.sub(r"\d+\s*%", "", option).strip()
            words = re.findall(r"[a-z]+", material_part)

            if words and all(word in actual for word in words):
                return True

        else:
            words = re.findall(r"[a-z]+", option)

            if words and all(word in actual for word in words):
                return True

    return False


def size_matches_html(html, required_size):
    if not clean_text(required_size):
        return True

    soup = BeautifulSoup(html, "html.parser")
    required = normalize_size(required_size)
    found_size_controls = False

    labels = soup.select('[id^="size_name_"][id$="_announce"]')
    for label in labels:
        found_size_controls = True
        text = clean_text(label.get_text(" ", strip=True))
        text = re.split(r"₹", text, maxsplit=1)[0].strip()

        if normalize_size(text) == required:
            return True

    radios = soup.select('input[role="radio"][aria-labelledby*="size_name_"]')
    for radio in radios:
        found_size_controls = True
        labelledby = radio.get("aria-labelledby", "")

        for label_id in labelledby.split():
            label = soup.find(id=label_id)
            if not label:
                continue

            text = clean_text(label.get_text(" ", strip=True))
            text = re.split(r"₹", text, maxsplit=1)[0].strip()

            if normalize_size(text) == required:
                return True

    container = soup.select_one("#variation_size_name")
    if container:
        found_size_controls = True

        elements = container.select(".a-button-text, button, label, span")
        for element in elements:
            text = clean_text(element.get_text(" ", strip=True))
            text = re.split(r"₹", text, maxsplit=1)[0].strip()

            if normalize_size(text) == required:
                return True

    if found_size_controls:
        return False

    return None


async def live_size_matches(page, required_size):
    if not clean_text(required_size):
        return True

    required = normalize_size(required_size)
    found_size_controls = False

    try:
        labels = page.locator('[id^="size_name_"][id$="_announce"]')
        count = await labels.count()

        for i in range(count):
            found_size_controls = True
            text = clean_text(await labels.nth(i).inner_text())
            text = re.split(r"₹", text, maxsplit=1)[0].strip()

            if normalize_size(text) == required:
                return True

    except Exception:
        pass

    try:
        radios = page.locator('input[role="radio"][aria-labelledby*="size_name_"]')
        count = await radios.count()

        for i in range(count):
            found_size_controls = True
            radio = radios.nth(i)
            labelledby = await radio.get_attribute("aria-labelledby") or ""

            for label_id in labelledby.split():
                try:
                    label = page.locator(f"#{label_id}").first
                    if await label.count() == 0:
                        continue

                    text = clean_text(await label.inner_text())
                    text = re.split(r"₹", text, maxsplit=1)[0].strip()

                    if normalize_size(text) == required:
                        return True
                except Exception:
                    continue

    except Exception:
        pass

    try:
        container = page.locator("#variation_size_name").first
        if await container.count() > 0:
            found_size_controls = True
            elements = container.locator(".a-button-text, button, label, span")
            count = await elements.count()

            for i in range(count):
                text = clean_text(await elements.nth(i).inner_text())
                text = re.split(r"₹", text, maxsplit=1)[0].strip()

                if normalize_size(text) == required:
                    return True

    except Exception:
        pass

    if found_size_controls:
        return False

    return None


def extract_price(html):
    soup = BeautifulSoup(html, "html.parser")

    selectors = [
        "#corePrice_feature_div span.a-offscreen",
        "#corePriceDisplay_desktop_feature_div span.a-offscreen",
        "#apex_desktop span.a-offscreen",
        "#priceblock_ourprice",
        "#priceblock_dealprice",
        "span.a-price span.a-offscreen",
        "span.a-price-whole",
    ]

    for selector in selectors:
        elements = soup.select(selector)

        for element in elements:
            price = parse_price(element.get_text(" ", strip=True))
            if price is not None:
                return price

    for selector in [
        "#corePrice_feature_div",
        "#corePriceDisplay_desktop_feature_div",
        "#apex_desktop",
    ]:
        container = soup.select_one(selector)
        if not container:
            continue

        price = parse_price(container.get_text(" ", strip=True))
        if price is not None:
            return price

    return None


def extract_title(html, fallback_title):
    soup = BeautifulSoup(html, "html.parser")

    title = soup.select_one("#productTitle")
    if title:
        text = clean_text(title.get_text(" ", strip=True))
        if text:
            return text

    return fallback_title


def extract_material(html):
    soup = BeautifulSoup(html, "html.parser")

    for row in soup.select("tr"):
        cells = row.find_all(["th", "td"], recursive=False)
        if len(cells) < 2:
            continue

        left = clean_text(cells[0].get_text(" ", strip=True)).lower()

        if left == "material composition":
            value = clean_text(cells[1].get_text(" ", strip=True))
            if value:
                return value

    for li in soup.select(
        "#detailBullets_feature_div li, "
        "#detailBulletsWrapper_feature_div li"
    ):
        text = clean_text(li.get_text(" ", strip=True))

        match = re.search(
            r"material composition\s*[:\-]?\s*(.+)",
            text,
            re.IGNORECASE,
        )

        if match:
            value = clean_text(match.group(1))
            if value:
                return value

    for row in soup.select(
        "#prodDetails tr, "
        "#productDetails tr, "
        "#productDetails_techSpec_section_1 tr"
    ):
        cells = row.find_all(["th", "td"], recursive=False)
        if len(cells) < 2:
            continue

        left = clean_text(cells[0].get_text(" ", strip=True)).lower()

        if left == "material composition":
            value = clean_text(cells[1].get_text(" ", strip=True))
            if value:
                return value

    text = soup.get_text("\n", strip=True)
    lines = [line.strip() for line in text.splitlines() if line.strip()]

    for i, line in enumerate(lines):
        if line.lower() == "material composition" and i + 1 < len(lines):
            value = clean_text(lines[i + 1])
            if value:
                return value

    return None


def get_user_requirements():
    result = {}

    root = tk.Tk()
    root.title("Amazon Product Finder")
    root.resizable(False, False)
    root.attributes("-topmost", True)

    frame = tk.Frame(root, padx=18, pady=18)
    frame.pack()

    product_var = tk.StringVar()
    material_var = tk.StringVar()
    size_var = tk.StringVar()
    min_price_var = tk.StringVar()
    max_price_var = tk.StringVar()

    fields = [
        ("Product / Category *", product_var),
        ("Material", material_var),
        ("Size", size_var),
        ("Minimum Price", min_price_var),
        ("Maximum Price", max_price_var),
    ]

    entries = []

    for row, (label_text, variable) in enumerate(fields):
        tk.Label(
            frame,
            text=label_text,
            anchor="w",
            width=20,
        ).grid(row=row, column=0, padx=(0, 10), pady=6, sticky="w")

        entry = tk.Entry(frame, textvariable=variable, width=38)
        entry.grid(row=row, column=1, pady=6, sticky="ew")
        entries.append(entry)

    def submit(event=None):
        product = clean_text(product_var.get())
        minimum = clean_text(min_price_var.get())
        maximum = clean_text(max_price_var.get())

        if not product:
            messagebox.showerror(
                "Missing product",
                "Product / Category is required.",
                parent=root,
            )
            entries[0].focus_set()
            return

        if minimum and not minimum.isdigit():
            messagebox.showerror(
                "Invalid minimum price",
                "Minimum Price must be a number.",
                parent=root,
            )
            return

        if maximum and not maximum.isdigit():
            messagebox.showerror(
                "Invalid maximum price",
                "Maximum Price must be a number.",
                parent=root,
            )
            return

        if minimum and maximum and int(minimum) > int(maximum):
            messagebox.showerror(
                "Invalid price range",
                "Minimum Price cannot be greater than Maximum Price.",
                parent=root,
            )
            return

        result.update(
            {
                "product": product,
                "material": clean_text(material_var.get()),
                "size": clean_text(size_var.get()),
                "min_price": minimum,
                "max_price": maximum,
            }
        )

        root.destroy()

    submit_button = tk.Button(
        frame,
        text="Search",
        width=14,
        command=submit,
    )
    submit_button.grid(row=len(fields), column=1, pady=(12, 0), sticky="e")

    root.bind("<Return>", submit)
    entries[0].focus_set()
    root.mainloop()

    if not result:
        raise SystemExit("Search cancelled.")

    return result


async def http_check(client, product, requirements):
    asin = product["asin"]
    fallback_title = product["title"]
    url = f"https://www.amazon.in/dp/{asin}"

    try:
        response = await client.get(url)

        if response.status_code != 200:
            return {
                "status": "fallback",
                "asin": asin,
                "title": fallback_title,
                "url": url,
            }

        html = response.text
        lower_html = html.lower()

        if (
            "captcha" in lower_html
            or "robot check" in lower_html
            or len(html) < 10000
        ):
            return {
                "status": "fallback",
                "asin": asin,
                "title": fallback_title,
                "url": url,
            }

        material = extract_material(html)
        title = extract_title(html, fallback_title)

        if requirements["material"] and not material:
            return {
                "status": "fallback",
                "asin": asin,
                "title": title,
                "url": url,
            }

        if not material_matches(material, requirements["material"]):
            return {
                "status": "no_match",
                "asin": asin,
                "title": title,
                "material": material,
                "price": None,
                "url": url,
            }

        size_result = size_matches_html(html, requirements["size"])

        if size_result is None and requirements["size"]:
            return {
                "status": "fallback",
                "asin": asin,
                "title": title,
                "url": url,
            }

        if size_result is False:
            return {
                "status": "no_match",
                "asin": asin,
                "title": title,
                "material": material,
                "price": None,
                "url": url,
            }

        actual_price = extract_price(html)

        if (requirements["min_price"] or requirements["max_price"]) and actual_price is None:
            return {
                "status": "fallback",
                "asin": asin,
                "title": title,
                "url": url,
            }

        if not price_matches(
            actual_price,
            requirements["min_price"],
            requirements["max_price"],
        ):
            return {
                "status": "no_match",
                "asin": asin,
                "title": title,
                "material": material,
                "price": actual_price,
                "url": url,
            }

        return {
            "status": "success",
            "asin": asin,
            "title": title,
            "material": material,
            "price": actual_price,
            "url": url,
        }

    except Exception as exc:
        return {
            "status": "fallback",
            "asin": asin,
            "title": fallback_title,
            "url": url,
            "error": str(exc),
        }


async def playwright_check(page, product, requirements):
    asin = product["asin"]
    fallback_title = product["title"]
    url = f"https://www.amazon.in/dp/{asin}"

    try:
        await page.goto(
            url,
            wait_until="domcontentloaded",
            timeout=15000,
        )

        await page.wait_for_timeout(800)

        title = fallback_title

        try:
            title_text = await page.locator("#productTitle").inner_text(timeout=2500)
            if clean_text(title_text):
                title = clean_text(title_text)
        except Exception:
            pass

        material = None

        try:
            body_text = await page.locator("body").inner_text(timeout=2500)
            lines = [line.strip() for line in body_text.splitlines() if line.strip()]

            for i, line in enumerate(lines):
                if line.lower() == "material composition" and i + 1 < len(lines):
                    value = clean_text(lines[i + 1])
                    if value:
                        material = value
                        break
        except Exception:
            pass

        if not material:
            try:
                row = page.locator(
                    "div.a-fixed-left-grid"
                ).filter(
                    has_text="Material composition"
                ).first

                if await row.count() > 0:
                    material = clean_text(
                        await row.locator(
                            "div.a-col-right span.a-color-base"
                        ).inner_text(timeout=2500)
                    )
            except Exception:
                pass

        if requirements["material"] and not material:
            return None

        if not material_matches(material, requirements["material"]):
            return None

        size_result = await live_size_matches(page, requirements["size"])

        if size_result is None and requirements["size"]:
            return None

        if size_result is False:
            return None

        actual_price = None

        for selector in [
            "#corePrice_feature_div span.a-offscreen",
            "#corePriceDisplay_desktop_feature_div span.a-offscreen",
            "#apex_desktop span.a-offscreen",
            "#priceblock_ourprice",
            "#priceblock_dealprice",
            "span.a-price span.a-offscreen",
            "span.a-price-whole",
        ]:
            try:
                locator = page.locator(selector)
                count = await locator.count()

                for i in range(count):
                    text = await locator.nth(i).inner_text()
                    actual_price = parse_price(text)
                    if actual_price is not None:
                        break

                if actual_price is not None:
                    break
            except Exception:
                continue

        if (requirements["min_price"] or requirements["max_price"]) and actual_price is None:
            return None

        if not price_matches(
            actual_price,
            requirements["min_price"],
            requirements["max_price"],
        ):
            return None

        return {
            "asin": asin,
            "title": title,
            "material": material,
            "price": actual_price,
            "url": url,
        }

    except (PlaywrightTimeoutError, Exception):
        return None


async def is_search_results_page(page):
    try:
        url = page.url.lower()
        return "amazon.in/s" in url
    except Exception:
        return False


async def highlight_product(search_page, asin):
    if not await is_search_results_page(search_page):
        return False

    try:
        result = await search_page.evaluate(
            """
            asin => {
                const nodes = Array.from(
                    document.querySelectorAll(`[data-asin="${CSS.escape(asin)}"]`)
                );

                const cards = [];

                for (const node of nodes) {
                    const card =
                        node.closest('div[data-component-type="s-search-result"]') ||
                        (node.matches('div[data-component-type="s-search-result"]') ? node : null);

                    if (!card) continue;

                    const rect = card.getBoundingClientRect();
                    const style = window.getComputedStyle(card);

                    if (
                        rect.width > 0 &&
                        rect.height > 0 &&
                        style.display !== 'none' &&
                        style.visibility !== 'hidden'
                    ) {
                        cards.push(card);
                    }
                }

                const card = cards[0] || null;

                if (!card) {
                    return false;
                }

                const alreadyHighlighted =
                    card.getAttribute('data-amazon-helper-match') === 'true' &&
                    card.style.getPropertyValue('border') &&
                    card.style.getPropertyValue('background-color') &&
                    card.style.getPropertyValue('box-shadow');

                card.setAttribute('data-amazon-helper-match', 'true');
                card.style.setProperty('border', '4px solid green', 'important');
                card.style.setProperty('background-color', '#d4ffd4', 'important');
                card.style.setProperty('box-shadow', '0 0 10px green', 'important');

                return alreadyHighlighted ? 'already' : 'applied';
            }
            """,
            asin,
        )

        if result == "applied":
            print(f"Highlighted: {asin}")
            return True

        return result == "already"

    except Exception as exc:
        return False


async def restore_all_highlights(search_page, highlighted_asins, attempts=3):
    if not await is_search_results_page(search_page):
        return

    for _ in range(attempts):
        if not await is_search_results_page(search_page):
            return

        for asin in list(highlighted_asins):
            await highlight_product(search_page, asin)

        await search_page.wait_for_timeout(400)


async def highlight_refresh_loop(search_page, highlighted_asins, stop_event):
    while not stop_event.is_set():
        try:
            if await is_search_results_page(search_page) and highlighted_asins:
                for asin in list(highlighted_asins):
                    await highlight_product(search_page, asin)
        except Exception:
            pass

        try:
            await asyncio.wait_for(stop_event.wait(), timeout=1.5)
        except asyncio.TimeoutError:
            continue


async def install_navigation_restore(search_page, highlighted_asins):
    async def on_frame_navigated(frame):
        if frame != search_page.main_frame:
            return

        try:
            if "amazon.in/s" not in search_page.url.lower():
                return

            await search_page.wait_for_timeout(700)
            await restore_all_highlights(
                search_page,
                highlighted_asins,
                attempts=3,
            )
        except Exception:
            pass

    search_page.on("framenavigated", lambda frame: asyncio.create_task(on_frame_navigated(frame)))


async def main():
    requirements = get_user_requirements()

    print()
    print("========================================")
    print("AMAZON PRODUCT FINDER")
    print("========================================")
    print("Product / Category:", requirements["product"])
    print("Material:", requirements["material"] or "Any")
    print("Size:", requirements["size"] or "Any")
    print("Minimum Price:", requirements["min_price"] or "Any")
    print("Maximum Price:", requirements["max_price"] or "Any")
    print()

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)
        search_page = await browser.new_page()

        await search_page.goto("https://www.amazon.in", wait_until="domcontentloaded")

        await search_page.wait_for_selector("#twotabsearchtextbox")
        await search_page.fill(
            "#twotabsearchtextbox",
            requirements["product"],
        )
        await search_page.press("#twotabsearchtextbox", "Enter")
        await search_page.wait_for_timeout(2500)

        highlighted_asins = set()
        stop_refresh = asyncio.Event()

        await install_navigation_restore(search_page, highlighted_asins)
        highlight_task = asyncio.create_task(
            highlight_refresh_loop(
                search_page,
                highlighted_asins,
                stop_refresh,
            )
        )

        cards = search_page.locator("div[data-asin]")
        card_count = await cards.count()

        print("Currently loaded product cards:", card_count)

        products = []
        seen_asins = set()

        for i in range(card_count):
            card = cards.nth(i)

            try:
                asin = await card.get_attribute("data-asin")
            except Exception:
                continue

            if not asin or asin in seen_asins:
                continue

            seen_asins.add(asin)

            title = None

            try:
                locator = card.locator("h2[aria-label] span").first
                if await locator.count() > 0:
                    text = clean_text(await locator.inner_text(timeout=1000))
                    if text:
                        title = text
            except Exception:
                pass

            if not title:
                for selector in [
                    "h2 span",
                    "h2",
                    "[data-cy='title'] span",
                ]:
                    try:
                        locator = card.locator(selector).first
                        if await locator.count() > 0:
                            text = clean_text(await locator.inner_text(timeout=700))
                            if text:
                                title = text
                                break
                    except Exception:
                        continue

            if not title:
                title = f"ASIN {asin}"

            products.append(
                {
                    "asin": asin,
                    "title": title,
                }
            )

        print("Unique products to check:", len(products))

        cookies = await search_page.context.cookies()
        cookie_dict = {cookie["name"]: cookie["value"] for cookie in cookies}

        user_agent = await search_page.evaluate("navigator.userAgent")

        headers = {
            "User-Agent": user_agent,
            "Accept": (
                "text/html,application/xhtml+xml,application/xml;q=0.9,"
                "image/avif,image/webp,*/*;q=0.8"
            ),
            "Accept-Language": "en-IN,en;q=0.9",
            "Cache-Control": "no-cache",
            "Referer": "https://www.amazon.in/",
        }

        client = httpx.AsyncClient(
            headers=headers,
            cookies=cookie_dict,
            follow_redirects=True,
            timeout=HTTP_TIMEOUT,
        )

        fallback_browser = await p.chromium.launch(headless=True)
        fallback_context = await fallback_browser.new_context(user_agent=user_agent)

        fallback_pages = [
            await fallback_context.new_page()
            for _ in range(FALLBACK_CONCURRENT_CHECKS)
        ]

        matches = []
        matched_asins = set()
        fallback_products = []

        async def handle_success(result, source_label=None):
            asin = result["asin"]

            if asin in matched_asins:
                return

            matched_asins.add(asin)
            highlighted_asins.add(asin)
            matches.append(result)

            if source_label:
                print(source_label, asin)

            print(">>> MATCH FOUND <<<")

            await highlight_product(search_page, asin)

        semaphore = asyncio.Semaphore(HTTP_CONCURRENT_CHECKS)

        async def process_http(product):
            async with semaphore:
                result = await http_check(client, product, requirements)
                return product, result

        print()
        print("==============================")
        print("STARTING HTTP CHECKS")
        print("==============================")

        http_tasks = [
            asyncio.create_task(process_http(product))
            for product in products
        ]

        for task in asyncio.as_completed(http_tasks):
            product, result = await task

            if result["status"] == "fallback":
                fallback_products.append(product)
                continue

            title = result.get("title", product["title"])
            material = result.get("material")
            price = result.get("price")
            asin = result["asin"]

            print()
            print("Checking:", asin)
            print("Title:", title)
            print("Material:", material or "Not found")

            if requirements["size"]:
                print("Size", requirements["size"] + ":", "FOUND")

            if price is not None:
                print("Price:", price)
            else:
                print("Price: Not found")

            print("----------------")

            if result["status"] == "success":
                await handle_success(result)

        print()
        print("HTTP checks needing fallback:", len(fallback_products))

        async def fallback_worker(product, page):
            result = await playwright_check(page, product, requirements)

            print()
            print("Fallback:", product["asin"])

            if not result:
                print("No match / could not verify")
                print("----------------")
                return

            print("Title:", result["title"])
            print("Material:", result.get("material") or "Not found")

            if requirements["size"]:
                print("Size", requirements["size"] + ": FOUND")

            if result.get("price") is not None:
                print("Price:", result["price"])
            else:
                print("Price: Not found")

            print("----------------")
            await handle_success(result, source_label="MATCH FROM FALLBACK:")

        for start in range(
            0,
            len(fallback_products),
            FALLBACK_CONCURRENT_CHECKS,
        ):
            batch = fallback_products[
                start:start + FALLBACK_CONCURRENT_CHECKS
            ]

            tasks = [
                fallback_worker(product, fallback_pages[i])
                for i, product in enumerate(batch)
            ]

            await asyncio.gather(*tasks)

        print()
        print("==============================")
        print("FINAL HIGHLIGHT PASS")
        print("==============================")

        if await is_search_results_page(search_page):
            await restore_all_highlights(
                search_page,
                highlighted_asins,
                attempts=4,
            )

        print("Final highlighted products:", len(highlighted_asins))

        await client.aclose()
        await fallback_context.close()
        await fallback_browser.close()

        stop_refresh.set()
        try:
            await highlight_task
        except Exception:
            pass

        print()
        print("==============================")
        print("FINISHED")
        print("==============================")
        print("Products collected:", len(products))
        print("Matches:", len(matches))

        print()
        print("==============================")
        print("MATCHING PRODUCTS")
        print("==============================")

        for product in matches:
            print()
            print(product["title"])
            print("Material:", product.get("material") or "Not found")
            if product.get("price") is not None:
                print("Price:", product["price"])
            print(product["url"])

        input("\nPress Enter to close...")
        await browser.close()


if __name__ == "__main__":
    asyncio.run(main())

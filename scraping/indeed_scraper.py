from pathlib import Path
import pandas as pd
import time
from urllib.parse import quote_plus
from playwright.sync_api import sync_playwright, Page

from .config import settings
from utils import setup_logger

logger = setup_logger()

USER_DATA_DIR = Path(settings.playwright_user_data_dir)


def _check_captcha(page: Page) -> bool:
    """
    Vérifie si Indeed affiche un captcha.
    """
    try:
        if page.query_selector("iframe[src*='captcha']"):
            return True
        if "captcha" in page.url.lower():
            return True
    except:
        pass
    return False


def _wait_for_manual_captcha(page: Page, timeout: int = 300) -> bool:
    """
    Attend que l'utilisateur résolve le captcha manuellement.
    """
    logger.warning("Captcha détecté ! Résous-le dans le navigateur...")
    logger.info(f"Tu as {timeout} secondes pour le résoudre.")

    start_time = time.time()

    while time.time() - start_time < timeout:
        time.sleep(2)

        if not _check_captcha(page):
            logger.info("Captcha résolu ✅")
            return True

    logger.error("Timeout captcha ❌")
    return False


def scrape_indeed() -> pd.DataFrame:
    jobs_data = []
    USER_DATA_DIR.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as p:

        logger.info("Lancement navigateur avec profil persistant")

        context = p.chromium.launch_persistent_context(
            user_data_dir=str(USER_DATA_DIR),
            channel="chrome",
            headless=False,
            viewport={"width": 1920, "height": 1080},
            slow_mo=50,
            ignore_default_args=["--enable-automation"],
            args=[
                "--disable-blink-features=AutomationControlled",
                "--disable-infobars",
            ],
        )

        page: Page = context.new_page()

        base_url = (
            f"https://fr.indeed.com/jobs?"
            f"q={quote_plus(settings.query)}&"
            f"l={quote_plus(settings.location)}"
        )

        logger.info(f"Navigation vers {base_url}")
        page.goto(base_url, wait_until="domcontentloaded", timeout=120000)
        time.sleep(5)

        # Gestion captcha (une seule fois)
        if _check_captcha(page):
            if not _wait_for_manual_captcha(page):
                context.close()
                raise Exception("Captcha non résolu")

        page_count = 0
        max_pages = 5

        while len(jobs_data) < settings.max_results and page_count < max_pages:

            logger.info(f"Page {page_count + 1}")

            page.wait_for_selector("div.job_seen_beacon", timeout=20000)
            job_cards = page.query_selector_all("div.job_seen_beacon")

            for card in job_cards:

                if len(jobs_data) >= settings.max_results:
                    break

                try:
                    title_el = card.query_selector("h2.jobTitle span")
                    company_el = card.query_selector("span.companyName")
                    location_el = card.query_selector("div.companyLocation")
                    link_el = card.query_selector("a")

                    title = title_el.inner_text().strip() if title_el else ""
                    company = company_el.inner_text().strip() if company_el else ""
                    location = location_el.inner_text().strip() if location_el else ""

                    link = ""
                    if link_el:
                        href = link_el.get_attribute("href")
                        if href:
                            link = "https://fr.indeed.com" + href

                    description = ""

                    # Ouvre description dans nouvel onglet (évite DOM detach)
                    if link:
                        job_page = context.new_page()
                        job_page.goto(link, wait_until="domcontentloaded")
                        time.sleep(2)

                        desc_el = job_page.query_selector("#jobDescriptionText")
                        if desc_el:
                            description = desc_el.inner_text().strip()

                        job_page.close()

                    # éviter doublons
                    if not any(
                        j["title"] == title and j["company"] == company
                        for j in jobs_data
                    ):
                        jobs_data.append({
                            "title": title,
                            "company": company,
                            "location": location,
                            "description": description,
                            "url": link
                        })

                except Exception as e:
                    logger.warning(f"Erreur extraction job: {e}")
                    continue

            # pagination
            page_count += 1
            next_url = f"{base_url}&start={page_count * 10}"
            page.goto(next_url, wait_until="domcontentloaded")
            time.sleep(3)

        logger.info(f"{len(jobs_data)} offres collectées")

        context.close()

    return pd.DataFrame(jobs_data)
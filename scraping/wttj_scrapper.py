from typing import List, Dict
import pandas as pd
import time
from playwright.sync_api import sync_playwright, Page
from urllib.parse import quote_plus

BASE_URL = "https://www.welcometothejungle.com"


def build_search_url(query: str = "data analyst pricing") -> str:
    q = quote_plus(query)

    return (
        f"{BASE_URL}/fr/jobs?query={q}"
        "&refinementList[offices.country_code][0]=FR"
        "&refinementList[contract_type][0]=apprenticeship"
    )


def extract_jobs_from_page(page: Page) -> List[Dict]:
    jobs = []

    cards = page.query_selector_all('li[data-testid="search-results-list-item-wrapper"]')

    for card in cards:
        try:
            # IMPORTANT: prendre le <a> à l'intérieur
            link_el = card.query_selector("a")

            title_el = card.query_selector('[data-testid="job-title"]')
            company_el = card.query_selector('[data-testid="job-company"]')
            location_el = card.query_selector('[data-testid="job-location"]')

            href = link_el.get_attribute("href") if link_el else None

            job = {
                "title": title_el.inner_text().strip() if title_el else None,
                "company": company_el.inner_text().strip() if company_el else None,
                "location": location_el.inner_text().strip() if location_el else None,
                "url": BASE_URL + href if href else None
            }

            jobs.append(job)

        except Exception as e:
            print(f"Erreur extraction job: {e}")
            continue

    return jobs


def scroll_page(page: Page, max_scrolls: int = 1):
    for _ in range(max_scrolls):
        page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        time.sleep(2)


def scrape_jobs(query: str = "data analyst pricing", max_pages: int = 3) -> pd.DataFrame:
    all_jobs = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        page = browser.new_page()

        url = build_search_url(query)
        page.goto(url, wait_until="domcontentloaded")

        page.wait_for_selector(
            'li[data-testid="search-results-list-item-wrapper"]',
            timeout=15000
        )

        print("👉 Vérifie les filtres (toggle, etc.) dans le navigateur")
        input("Appuie sur ENTRÉE pour continuer...")
        for page_number in range(1, max_pages + 1):

            print(f"\n--- PAGE {page_number} ---")


            page.wait_for_selector(
                'li[data-testid="search-results-list-item-wrapper"]',
                timeout=15000
            )

            scroll_page(page)

            jobs = extract_jobs_from_page(page)
            print(f"{len(jobs)} jobs trouvés")

            all_jobs.extend(jobs)

            # 👉 cliquer sur "page suivante"
            try:
                # récupérer tous les boutons de pagination
                buttons = page.query_selector_all('a.sc-imZCey')

                next_button = None

                for btn in buttons:
                    aria_disabled = btn.get_attribute("aria-disabled")

                    # on prend le bouton actif
                    if aria_disabled == "false":
                        next_button = btn

                if next_button:
                    print("➡️ Page suivante")
                    next_button.click()
                    page.wait_for_load_state("domcontentloaded")
                    time.sleep(3)
                else:
                    print("❌ Plus de page")
                    break

            except Exception as e:
                print(f"Erreur pagination: {e}")
                break

        browser.close()

    df = pd.DataFrame(all_jobs).drop_duplicates(subset=["url"])
    print(f"\nTotal jobs collectés: {len(df)}")

    return df


def save_to_csv(df: pd.DataFrame, path: str = "jobs_wttj_data_alternance.csv"):
    df.to_csv(path, index=False, encoding="utf-8")
    print(f"Fichier sauvegardé: {path}")


def extract_job_details(page) -> Dict:
    """
    Extrait description + experience d'une offre
    """

    def safe_text(selector):
        el = page.query_selector(selector)
        return el.inner_text().strip() if el else None

    description = safe_text('[data-testid="job-section-description"]')
    experience = safe_text('[data-testid="job-section-experience"]')

    return {
        "description": description,
        "experience": experience
    }


def enrich_dataframe(df: pd.DataFrame, delay: float = 1.5) -> pd.DataFrame:
    """
    Visite chaque URL et enrichit le dataset
    """

    results = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        page = browser.new_page()

        for i, row in df.iterrows():
            url = row["url"]

            print(f"[{i+1}/{len(df)}] Scraping: {url}")

            try:
                page.goto(url, wait_until="domcontentloaded")
                page.wait_for_timeout(2000)

                details = extract_job_details(page)

                results.append({
                    **row.to_dict(),
                    **details
                })

            except Exception as e:
                print(f"Erreur sur {url}: {e}")
                results.append({
                    **row.to_dict(),
                    "description": None,
                    "experience": None
                })

            time.sleep(delay)  # éviter blocage

        browser.close()

    return pd.DataFrame(results)

def main():
    df = scrape_jobs(query="data analyst", max_pages=4)

    df_enriched = enrich_dataframe(df)

    df_enriched.to_csv("jobs_wttj_full.csv", index=False)


if __name__ == "__main__":
    main()
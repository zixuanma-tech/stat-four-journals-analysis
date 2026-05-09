import os
import time

import requests
import pandas as pd
import feedparser


# AOS one-year metadata crawler
# Current version: paper metadata + citations + authors + institutions + OpenAlex topics + arXiv id/url

YEAR = 2026
JOURNAL_NAME = "The Annals of Statistics"

OPENALEX_SOURCES_URL = "https://api.openalex.org/sources"
OPENALEX_WORKS_URL = "https://api.openalex.org/works"
ARXIV_API_URL = "http://export.arxiv.org/api/query"

OUTPUT_PATH = f"data_sample/aos_{YEAR}_metadata.csv"

OPENALEX_API_KEY = os.getenv("OPENALEX_API_KEY")

ITEM_SEP = " | "


def add_openalex_key(params):
    if OPENALEX_API_KEY:
        params["api_key"] = OPENALEX_API_KEY
    return params


def get_json(url, params, sleep_seconds=0.5):
    params = add_openalex_key(params)

    response = requests.get(url, params=params, timeout=60)
    print("status:", response.status_code)

    response.raise_for_status()
    time.sleep(sleep_seconds)

    return response.json()


def get_names_and_count(items):
 
    if not isinstance(items, list):
        return "", 0

    names = []

    for item in items:
        if isinstance(item, dict):
            name = (
                item.get("display_name")
                or item.get("name")
                or item.get("keyword")
            )
            if name:
                names.append(str(name))

    names = sorted(set(names))

    return ITEM_SEP.join(names), len(names)


def find_aos_source_id():
    params = {
        "search": JOURNAL_NAME,
        "per-page": 5,
    }

    data = get_json(OPENALEX_SOURCES_URL, params)
    results = data.get("results", [])

    if not results:
        raise ValueError("No source candidates found.")

    print("source candidates:")
    for i, source in enumerate(results):
        print(i, source.get("display_name"), source.get("id"), source.get("issn_l"))

    for source in results:
        display_name = (source.get("display_name") or "").lower()
        if "annals of statistics" in display_name:
            print("selected source:", source.get("display_name"), source.get("id"))
            return source.get("id")

    selected = results[0]
    print("selected by fallback:", selected.get("display_name"), selected.get("id"))
    return selected.get("id")


def parse_work(work):
    authorships = work.get("authorships") or []

    author_names = []
    author_ids = []
    institution_names = []

    for authorship in authorships:
        author = authorship.get("author") or {}

        author_name = author.get("display_name")
        author_id = author.get("id")

        if author_name:
            author_names.append(author_name)
        if author_id:
            author_ids.append(author_id)

        institutions = authorship.get("institutions") or []
        for inst in institutions:
            inst_name = inst.get("display_name")
            if inst_name:
                institution_names.append(inst_name)

    primary_location = work.get("primary_location") or {}
    source = primary_location.get("source") or {}

    citation_percentile = None
    citation_obj = work.get("citation_normalized_percentile")
    if isinstance(citation_obj, dict):
        citation_percentile = citation_obj.get("value")

    keywords, keyword_count = get_names_and_count(work.get("keywords"))
    openalex_topics, topic_count = get_names_and_count(work.get("topics"))

    primary_topic_obj = work.get("primary_topic") or {}
    primary_topic = primary_topic_obj.get("display_name")
    primary_topic_count = 1 if primary_topic else 0

    return {
        "openalex_work_id": work.get("id"),
        "journal": source.get("display_name"),
        "publication_year": work.get("publication_year"),
        "publication_date": work.get("publication_date"),
        "title": work.get("display_name"),
        "doi": work.get("doi"),

        "cited_by_count": work.get("cited_by_count"),
        "citation_percentile": citation_percentile,

        "keywords": keywords,
        "keyword_count": keyword_count,

        "openalex_topics": openalex_topics,
        "topic_count": topic_count,

        "primary_topic": primary_topic,
        "primary_topic_count": primary_topic_count,

        "author_count": len(author_names),
        "author_names": ITEM_SEP.join(author_names),
        "author_ids": ITEM_SEP.join(author_ids),

        "institution_names": ITEM_SEP.join(sorted(set(institution_names))),
        "num_institutions": len(set(institution_names)),
    }


def fetch_aos_works(source_id):
    rows = []
    cursor = "*"

    while True:
        params = {
            "filter": ",".join([
                f"primary_location.source.id:{source_id}",
                f"from_publication_date:{YEAR}-01-01",
                f"to_publication_date:{YEAR}-12-31",
                "type:article",
            ]),
            "per-page": 100,
            "cursor": cursor,
            "select": ",".join([
                "id",
                "doi",
                "display_name",
                "publication_year",
                "publication_date",
                "cited_by_count",
                "citation_normalized_percentile",
                "authorships",
                "primary_location",
                "keywords",
                "topics",
                "primary_topic",
            ]),
        }

        data = get_json(OPENALEX_WORKS_URL, params)
        works = data.get("results", [])

        if not works:
            break

        for work in works:
            rows.append(parse_work(work))

        cursor = data.get("meta", {}).get("next_cursor")
        if not cursor:
            break

    df = pd.DataFrame(rows)

    if df.empty:
        raise ValueError("No works found. Check journal source id or year.")

    return df


def search_arxiv_by_title(title):
    if not isinstance(title, str) or not title.strip():
        return None

    params = {
        "search_query": f'ti:"{title}"',
        "start": 0,
        "max_results": 1,
    }

    response = requests.get(ARXIV_API_URL, params=params, timeout=60)
    print("arXiv:", response.status_code, "|", title[:70])

    response.raise_for_status()

    feed = feedparser.parse(response.text)

    if not feed.entries:
        return None

    entry = feed.entries[0]
    arxiv_url = entry.id
    arxiv_id = arxiv_url.split("/abs/")[-1]

    return {
        "arxiv_id": arxiv_id,
        "arxiv_url": arxiv_url,
    }


def add_arxiv_info(df, max_check=None):
    arxiv_ids = []
    arxiv_urls = []
    arxiv_statuses = []

    for i, row in df.iterrows():
        if max_check is not None and i >= max_check:
            arxiv_ids.append(None)
            arxiv_urls.append(None)
            arxiv_statuses.append("not_checked")
            continue

        try:
            result = search_arxiv_by_title(row["title"])

            if result is None:
                arxiv_ids.append(None)
                arxiv_urls.append(None)
                arxiv_statuses.append("not_found")
            else:
                arxiv_ids.append(result["arxiv_id"])
                arxiv_urls.append(result["arxiv_url"])
                arxiv_statuses.append("matched")

            time.sleep(3)

        except Exception as e:
            arxiv_ids.append(None)
            arxiv_urls.append(None)
            arxiv_statuses.append("error: " + str(e))

    df["arxiv_id"] = arxiv_ids
    df["arxiv_url"] = arxiv_urls
    df["arxiv_match_status"] = arxiv_statuses

    return df


def add_paper_id(df):
    df = df.reset_index(drop=True)

    df["paper_id"] = [
        f"AOS_{YEAR}_{i + 1:03d}"
        for i in range(len(df))
    ]

    cols = ["paper_id"] + [c for c in df.columns if c != "paper_id"]
    return df[cols]


def main():
    os.makedirs("data_sample", exist_ok=True)

    print("Step1: finding AOS source id")
    source_id = find_aos_source_id()

    print("Step2: fetching papers")
    df = fetch_aos_works(source_id)
    print("papers:", len(df))

    print("Step3: matching arXiv ids")
    df = add_arxiv_info(df, max_check=None)

    df = add_paper_id(df)
    df.to_csv(OUTPUT_PATH, index=False, encoding="utf-8-sig")

    print("saved:", OUTPUT_PATH)

    print("\npreview:")
    print(df[[
        "paper_id",
        "title",
        "cited_by_count",
        "citation_percentile",
        "keyword_count",
        "topic_count",
        "primary_topic_count",
        "arxiv_match_status",
    ]].head())

    print("\narXiv match status:")
    print(df["arxiv_match_status"].value_counts(dropna=False))


if __name__ == "__main__":
    main()
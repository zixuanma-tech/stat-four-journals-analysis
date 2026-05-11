import os
import time

import requests
import pandas as pd
import feedparser


# Four statistics journals metadata crawler
# Range: 2023-2026
# Current version: metadata + citations + authors + institutions + OpenAlex topics + arXiv id/url

START_YEAR = 2023
END_YEAR = 2026

JOURNALS = [
    {
        "short": "AOS",
        "name": "The Annals of Statistics",
    },
    {
        "short": "BIO",
        "name": "Biometrika",
    },
    {
        "short": "JASA",
        "name": "Journal of the American Statistical Association",
    },
    {
        "short": "JRSSB",
        "name": "Journal of the Royal Statistical Society Series B Statistical Methodology",
    },
]

OPENALEX_SOURCES_URL = "https://api.openalex.org/sources"
OPENALEX_WORKS_URL = "https://api.openalex.org/works"
ARXIV_API_URL = "http://export.arxiv.org/api/query"

OUTPUT_PATH = f"data_sample/stat4_{START_YEAR}_{END_YEAR}_metadata.csv"

OPENALEX_API_KEY = os.getenv("OPENALEX_API_KEY")

ITEM_SEP = " | "

ARXIV_SLEEP_SECONDS = 10


def add_openalex_key(params):
    if OPENALEX_API_KEY:
        params["api_key"] = OPENALEX_API_KEY
    return params


def get_json(url, params, sleep_seconds=0.5):
    params = add_openalex_key(params)

    response = requests.get(url, params=params, timeout=60)
    print("OpenAlex status:", response.status_code)

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


def find_source_id(journal_name):
    params = {
        "search": journal_name,
        "per-page": 5,
    }

    data = get_json(OPENALEX_SOURCES_URL, params)
    results = data.get("results", [])

    if not results:
        raise ValueError(f"No source candidates found for {journal_name}")

    print(f"\nsource candidates for {journal_name}:")
    for i, source in enumerate(results):
        print(i, source.get("display_name"), source.get("id"), source.get("issn_l"))

    target = journal_name.lower()

    for source in results:
        display_name = (source.get("display_name") or "").lower()
        if target in display_name or display_name in target:
            print("selected source:", source.get("display_name"), source.get("id"))
            return source.get("id"), source.get("display_name")

    selected = results[0]
    print("selected by fallback:", selected.get("display_name"), selected.get("id"))
    return selected.get("id"), selected.get("display_name")


def parse_work(work, journal_short):
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
    biblio = work.get("biblio") or {}

    citation_percentile = None
    citation_obj = work.get("citation_normalized_percentile")
    if isinstance(citation_obj, dict):
        value = citation_obj.get("value")
        if value is not None:
            citation_percentile = value * 100 if value <= 1 else value

    keywords, keyword_count = get_names_and_count(work.get("keywords"))
    openalex_topics, topic_count = get_names_and_count(work.get("topics"))

    primary_topic_obj = work.get("primary_topic") or {}
    primary_topic = primary_topic_obj.get("display_name")
    primary_topic_count = 1 if primary_topic else 0

    return {
        "journal_short": journal_short,
        "openalex_work_id": work.get("id"),
        "journal": source.get("display_name"),
        "work_type": work.get("type"),

        "publication_year": work.get("publication_year"),
        "publication_date": work.get("publication_date"),
        "volume": biblio.get("volume"),
        "issue": biblio.get("issue"),

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


def fetch_journal_works(source_id, journal_short):
    rows = []
    cursor = "*"

    while True:
        params = {
            "filter": ",".join([
                f"primary_location.source.id:{source_id}",
                f"from_publication_date:{START_YEAR}-01-01",
                f"to_publication_date:{END_YEAR}-12-31",
            ]),
            "per-page": 100,
            "cursor": cursor,
            "select": ",".join([
                "id",
                "doi",
                "display_name",
                "type",
                "publication_year",
                "publication_date",
                "biblio",
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
            rows.append(parse_work(work, journal_short))

        cursor = data.get("meta", {}).get("next_cursor")
        if not cursor:
            break

    return rows


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

    if response.status_code == 429:
        print("arXiv 429: too many requests. Sleep 60 seconds and skip this paper.")
        time.sleep(60)
        return None

    if response.status_code >= 500:
        print("arXiv server error. Sleep 30 seconds and skip this paper.")
        time.sleep(30)
        return None

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

            time.sleep(ARXIV_SLEEP_SECONDS)

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
        f"{row['journal_short']}_{int(row['publication_year'])}_{i + 1:04d}"
        for i, row in df.iterrows()
    ]

    cols = ["paper_id"] + [c for c in df.columns if c != "paper_id"]
    return df[cols]


def main():
    os.makedirs("data_sample", exist_ok=True)

    all_rows = []

    print("Step1: finding source ids and fetching works")

    for journal in JOURNALS:
        print("journal:", journal["short"], journal["name"])

        source_id, matched_source_name = find_source_id(journal["name"])

        rows = fetch_journal_works(
            source_id=source_id,
            journal_short=journal["short"],
        )

        print("fetched rows:", len(rows))
        all_rows.extend(rows)

    df = pd.DataFrame(all_rows)

    if df.empty:
        raise ValueError("No works found. Check journal names, source ids, or year range.")

    print("\nStep2: adding paper_id")
    df = add_paper_id(df)

    print("\nStep3: matching arXiv ids")
    df = add_arxiv_info(df, max_check=None)

    df.to_csv(OUTPUT_PATH, index=False, encoding="utf-8-sig")

    print("\nsaved:", OUTPUT_PATH)
    print("total rows:", len(df))

    print("\nwork type counts:")
    print(df["work_type"].value_counts(dropna=False))

    print("\njournal counts:")
    print(df["journal_short"].value_counts(dropna=False))

    print("\nyear counts:")
    print(df["publication_year"].value_counts(dropna=False).sort_index())

    print("\narXiv match status:")
    print(df["arxiv_match_status"].value_counts(dropna=False))

    print("\npreview:")
    print(df[[
        "paper_id",
        "journal_short",
        "work_type",
        "publication_year",
        "volume",
        "issue",
        "title",
        "cited_by_count",
        "citation_percentile",
        "keyword_count",
        "topic_count",
        "arxiv_match_status",
    ]].head())


if __name__ == "__main__":
    main()
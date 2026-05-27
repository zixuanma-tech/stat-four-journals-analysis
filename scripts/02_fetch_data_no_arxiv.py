import os
import time

import requests
import pandas as pd


START_YEAR = 2023
END_YEAR = 2026 
# 设置变量方便调试和修改

JOURNALS = [
    {"short": "AOS", "name": "The Annals of Statistics"},
    {"short": "BIO", "name": "Biometrika"},
    {"short": "JASA", "name": "Journal of the American Statistical Association"},
    {"short": "JRSSB", "name": "Journal of the Royal Statistical Society Series B Statistical Methodology"},
]

OPENALEX_SOURCES_URL = "https://api.openalex.org/sources"
OPENALEX_WORKS_URL = "https://api.openalex.org/works"

OUTPUT_PATH = f"data_sample/stat4_{START_YEAR}_{END_YEAR}_metadata.csv"

OPENALEX_API_KEY = os.getenv("OPENALEX_API_KEY")
ITEM_SEP = " | "
# 设置分隔符方便阅读


def key(params):
    if OPENALEX_API_KEY:
        params["api_key"] = OPENALEX_API_KEY
    return params


def json(url, params, sleep_seconds=1.0, max_retries=5):
    params = key(params)

    for attempt in range(1, max_retries + 1):
        try:
            response = requests.get(url, params=params, timeout=60)
            print("OpenAlex status:", response.status_code)

            if response.status_code == 429:
                wait_time = 30 * attempt
                print(f"429 Too Many Requests. Sleep {wait_time} seconds.")
                time.sleep(wait_time)
                continue

            if response.status_code >= 500:
                wait_time = 20 * attempt
                print(f"Server error. Sleep {wait_time} seconds.")
                time.sleep(wait_time)
                continue

            response.status()
            time.sleep(sleep_seconds)
            return response.json()

        except requests.exceptions.RequestException as e:
            wait_time = 20 * attempt
            print(f"Request failed: attempt {attempt}/{max_retries}")
            print(e)
            print(f"Sleep {wait_time} seconds.")
            time.sleep(wait_time)

    raise RuntimeError("OpenAlex request failed too many times.")
# 由于抓取数据过多，故异常情况时有发生，需纳入考虑

def namescount(items):
    if items is None:
        return "", 0

    names = []

    for item in items:
        name = item.get("display_name")
        if name:
            names.append(name)

    names = sorted(set(names))
    return ITEM_SEP.join(names), len(names)


def id(journal_name):
    params = {
        "search": journal_name,
        "per-page": 5,
    }

    data = json(OPENALEX_SOURCES_URL, params)
    results = data["results"]

    print(f"\nsource candidates for {journal_name}:")
    for i, source in enumerate(results):
        print(i, source.get("display_name"), source.get("id"), source.get("issn_l"))

    target = journal_name.lower()

    for source in results:
        display_name = source["display_name"]
        display_name_lower = display_name.lower()

        if target in display_name_lower or display_name_lower in target:
            print("selected source:", display_name, source["id"])
            return source["id"], display_name

    selected = results[0]
    print("selected by first result:", selected["display_name"], selected["id"])
    return selected["id"], selected["display_name"]


def parse(work, journal_short):
    author_names = []
    author_ids = []
    institution_names = []

    for authorship in work["authorships"]:
        author = authorship["author"]

        author_name = author.get("display_name")
        author_id = author.get("id")

        if author_name:
            author_names.append(author_name)

        if author_id:
            author_ids.append(author_id)

        for institution in authorship["institutions"]:
            institution_name = institution.get("display_name")
            if institution_name:
                institution_names.append(institution_name)

    source = work["primary_location"]["source"]
    biblio = work["biblio"]

    citation_percentile = None
    citation_info = work.get("citation_normalized_percentile")

    if citation_info is not None:
        value = citation_info.get("value")
        if value is not None:
            if value <= 1:
                citation_percentile = value * 100
            else:
                citation_percentile = value

    keywords, keyword_count = namescount(work.get("keywords"))
    openalex_topics, topic_count = namescount(work.get("topics"))

    primary_topic_info = work.get("primary_topic")

    if primary_topic_info is None:
        primary_topic = None
        primary_topic_count = 0
    else:
        primary_topic = primary_topic_info.get("display_name")
        primary_topic_count = 1

    row = {
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

    return row


def fetch(source_id, journal_short):
    rows = []
    cursor = "*"

    while True:
        filters = [
            f"primary_location.source.id:{source_id}",
            f"from_publication_date:{START_YEAR}-01-01",
            f"to_publication_date:{END_YEAR}-12-31",
        ]

        selected_fields = [
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
        ]

        params = {
            "filter": ",".join(filters),
            "per-page": 100,
            "cursor": cursor,
            "select": ",".join(selected_fields),
        }

        data = json(OPENALEX_WORKS_URL, params)
        works = data["results"]

        if len(works) == 0:
            break

        for work in works:
            row = parse(work, journal_short)
            rows.append(row)

        cursor = data["meta"]["next_cursor"]

        if cursor is None:
            break

    return rows


def addid(df):
    df = df.reset_index(drop=True)

    paper_ids = []

    for i, row in df.iterrows():
        journal_short = row["journal_short"]
        year = int(row["publication_year"])
        paper_id = f"{journal_short}_{year}_{i + 1:04d}"
        paper_ids.append(paper_id)

    df["paper_id"] = paper_ids

    columns = ["paper_id"]
    for column in df.columns:
        if column != "paper_id":
            columns.append(column)

    return df[columns]


def save(df):
    work_type_counts = df["work_type"].value_counts(dropna=False).reset_index()
    work_type_counts.columns = ["work_type", "count"]
    work_type_counts.to_csv(
        "data_sample/work_type_counts.csv",
        index=False,
        encoding="utf-8-sig",
    )

    journal_counts = df["journal_short"].value_counts(dropna=False).reset_index()
    journal_counts.columns = ["journal_short", "count"]
    journal_counts.to_csv(
        "data_sample/journal_counts.csv",
        index=False,
        encoding="utf-8-sig",
    )

    year_counts = df["publication_year"].value_counts(dropna=False).sort_index().reset_index()
    year_counts.columns = ["publication_year", "count"]
    year_counts.to_csv(
        "data_sample/year_counts.csv",
        index=False,
        encoding="utf-8-sig",
    )


def main():
    os.makedirs("data_sample", exist_ok=True)

    all_rows = []

    print("Step 1: fetch OpenAlex metadata")

    for journal in JOURNALS:
        print("journal:", journal["short"], journal["name"])

        source_id, source_name = id(journal["name"])
        print("matched source:", source_name)

        rows = fetch(source_id, journal["short"])

        print("fetched rows:", len(rows))
        all_rows.extend(rows)

    df = pd.DataFrame(all_rows)

    if df.empty:
        raise ValueError("No works found. Check journal names or year range.")

    print("\nStep 2: add paper_id")
    df = addid(df)

    df.to_csv(OUTPUT_PATH, index=False, encoding="utf-8-sig")
    save(df)

    print("\nsaved:", OUTPUT_PATH)
    print("total rows:", len(df))

    print("\nwork type counts:")
    print(df["work_type"].value_counts(dropna=False))

    print("\njournal counts:")
    print(df["journal_short"].value_counts(dropna=False))

    print("\nyear counts:")
    print(df["publication_year"].value_counts(dropna=False).sort_index())

if __name__ == "__main__":
    main()
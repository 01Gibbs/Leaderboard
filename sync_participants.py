#!/usr/bin/env python3

"""Sync exercise PR submissions and early-PR bonuses into participants.csv."""

import csv
import json
import os
import re
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path


TRACKS = {
    "fizzbuzz": "meswright/excersize-1",
    "rest_api": "AtulKumarSharma79/Onboardingtracker",
    "framework_upgrade": "AtulKumarSharma79/Frameworkupgrade",
}
CSV_PATH = Path(__file__).with_name("participants.csv")
PER_PAGE = 100
FIELDS = [
    "name",
    "github_username",
    "fizzbuzz",
    "rest_api",
    "framework_upgrade",
    "stretch",
    "pr_stretch",
    "helped",
]


def canonical_header(value):
    key = re.sub(r"[\s-]+", "_", value.strip().lower())
    return {
        "frameworkupgrade": "framework_upgrade",
        "restapi": "rest_api",
        "githubusername": "github_username",
        "container_image": "fizzbuzz",
        "prstretch": "pr_stretch",
    }.get(key, key)


def fetch_pr_authors(repository):
    api_url = f"https://api.github.com/repos/{repository}/pulls"
    prs = []
    page = 1
    while True:
        params = urllib.parse.urlencode({
            "state": "all",
            "sort": "created",
            "direction": "asc",
            "per_page": PER_PAGE,
            "page": page,
        })
        request = urllib.request.Request(
            f"{api_url}?{params}",
            headers={
                "Accept": "application/vnd.github+json",
                "User-Agent": "Leaderboard-CSV-Sync",
            },
        )
        with urllib.request.urlopen(request, timeout=30) as response:
            batch = json.load(response)
        if not isinstance(batch, list):
            raise ValueError(f"GitHub returned an unexpected PR response for {repository}")
        prs.extend(
            pr for pr in batch
            if (pr.get("user") or {}).get("login") and pr.get("created_at")
        )
        if len(batch) < PER_PAGE:
            break
        page += 1

    prs.sort(key=lambda pr: (pr["created_at"], pr["number"]))
    authors = [pr["user"]["login"] for pr in prs]
    return authors, [login.casefold() for login in authors[:3]]


def sync_csv(csv_path=CSV_PATH, fetcher=fetch_pr_authors):
    authors_by_track = {}
    bonus_by_track = {}
    all_authors = []
    seen_authors = set()
    for track, repository in TRACKS.items():
        authors, first_three = fetcher(repository)
        authors_by_track[track] = {login.casefold() for login in authors}
        bonus_by_track[track] = first_three
        for login in authors:
            normalized = login.casefold()
            if normalized not in seen_authors:
                all_authors.append(login)
                seen_authors.add(normalized)

    with csv_path.open("r", encoding="utf-8-sig", newline="") as source:
        table = list(csv.reader(source))
    if not table:
        raise ValueError(f"{csv_path.name} is empty")

    old_headers = [canonical_header(value) for value in table[0]]
    if len(set(old_headers)) != len(old_headers):
        raise ValueError(f"{csv_path.name} has duplicate columns after header normalization")
    if "name" not in old_headers:
        raise ValueError(f"{csv_path.name} must have a 'name' column")

    old_indexes = {key: i for i, key in enumerate(old_headers)}
    rows_by_login = {}
    unmatched_rows = []
    for source_row in table[1:]:
        if not any(value.strip() for value in source_row):
            continue
        values = {
            key: source_row[index].strip() if index < len(source_row) else ""
            for key, index in old_indexes.items()
        }
        row = {field: values.get(field, "") for field in FIELDS}
        login = row["github_username"].removeprefix("@").casefold()
        if login:
            if login in rows_by_login:
                raise ValueError(f"Duplicate github_username in CSV: {row['github_username']}")
            row["name"] = row["name"] or row["github_username"].removeprefix("@")
            rows_by_login[login] = row
        else:
            row["pr_stretch"] = "0"
            unmatched_rows.append(row)

    for login in all_authors:
        normalized = login.casefold()
        if normalized not in rows_by_login:
            rows_by_login[normalized] = {
                field: "" for field in FIELDS
            }
            rows_by_login[normalized]["name"] = login
            rows_by_login[normalized]["github_username"] = login

    for login, row in rows_by_login.items():
        for track in TRACKS:
            if row[track].strip().lower() != "correct":
                row[track] = "submitted" if login in authors_by_track[track] else "none"
        row["pr_stretch"] = str(
            sum(bonus_by_track[track].count(login) for track in TRACKS)
        )

    ordered_rows = [rows_by_login[login.casefold()] for login in all_authors]
    ordered_rows.extend(
        row for login, row in rows_by_login.items()
        if login not in seen_authors
    )
    ordered_rows.extend(unmatched_rows)

    fd, temp_name = tempfile.mkstemp(
        prefix=f".{csv_path.name}.", suffix=".tmp", dir=csv_path.parent
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as output:
            writer = csv.DictWriter(output, fieldnames=FIELDS, lineterminator="\n")
            writer.writeheader()
            writer.writerows(ordered_rows)
        os.replace(temp_name, csv_path)
    except Exception:
        try:
            os.unlink(temp_name)
        except FileNotFoundError:
            pass
        raise

    print(
        f"Updated {csv_path.name}: {len(all_authors)} PR authors; "
        f"{sum(len(authors) for authors in bonus_by_track.values())} first-three-PR bonuses assigned."
    )


if __name__ == "__main__":
    try:
        sync_csv()
    except (OSError, urllib.error.URLError, ValueError, KeyError) as error:
        raise SystemExit(f"Could not sync participants: {error}") from error

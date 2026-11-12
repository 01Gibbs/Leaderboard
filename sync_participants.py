#!/usr/bin/env python3
"""Order participants by their first PR and add any missing PR authors."""

import csv
import json
import os
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path


REPOSITORY = "AtulKumarSharma79/Onboardingtracker"
API_URL = f"https://api.github.com/repos/{REPOSITORY}/pulls"
CSV_PATH = Path(__file__).with_name("participants.csv")


def fetch_pr_authors():
    authors = []
    page = 1
    while True:
        params = urllib.parse.urlencode({
            "state": "all",
            "sort": "created",
            "direction": "asc",
            "per_page": 100,
            "page": page,
        })
        request = urllib.request.Request(
            f"{API_URL}?{params}",
            headers={
                "Accept": "application/vnd.github+json",
                "User-Agent": "Leaderboard-CSV-Sync",
            },
        )
        with urllib.request.urlopen(request, timeout=30) as response:
            batch = json.load(response)
        if not isinstance(batch, list):
            raise ValueError("GitHub returned an unexpected PR response")
        authors.extend(
            (pr["user"]["login"], pr["created_at"], pr["number"])
            for pr in batch
            if pr.get("user", {}).get("login")
        )
        if len(batch) < 100:
            break
        page += 1

    authors.sort(key=lambda pr: (pr[1], pr[2]))
    ordered_logins = []
    seen = set()
    for login, _, _ in authors:
        normalized = login.casefold()
        if normalized not in seen:
            seen.add(normalized)
            ordered_logins.append(login)
    return ordered_logins


def sync_csv():
    ordered_logins = fetch_pr_authors()
    with CSV_PATH.open("r", encoding="utf-8-sig", newline="") as source:
        table = list(csv.reader(source))
    if not table:
        raise ValueError(f"{CSV_PATH.name} is empty")

    header = table[0]
    normalized_header = [column.strip().lower() for column in header]
    if "name" not in normalized_header:
        raise ValueError(f"{CSV_PATH.name} must have a 'name' column")
    if "github_username" not in normalized_header:
        header.append("github_username")
        normalized_header.append("github_username")

    name_index = normalized_header.index("name")
    username_index = normalized_header.index("github_username")
    width = len(header)
    existing_rows = []
    for row in table[1:]:
        if not any(value.strip() for value in row):
            continue
        row = row[:width] + [""] * max(0, width - len(row))
        existing_rows.append(row)

    rows_by_login = {}
    for row in existing_rows:
        login = row[username_index].strip().removeprefix("@").casefold()
        if login:
            rows_by_login.setdefault(login, []).append(row)

    ordered_rows = []
    used_rows = set()
    for login in ordered_logins:
        matches = rows_by_login.get(login.casefold(), [])
        if matches:
            for row in matches:
                ordered_rows.append(row)
                used_rows.add(id(row))
        else:
            row = [""] * width
            row[name_index] = login
            row[username_index] = login
            ordered_rows.append(row)

    ordered_rows.extend(row for row in existing_rows if id(row) not in used_rows)
    fd, temp_name = tempfile.mkstemp(
        prefix=f".{CSV_PATH.name}.", suffix=".tmp", dir=CSV_PATH.parent
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as output:
            writer = csv.writer(output, lineterminator="\n")
            writer.writerow(header)
            writer.writerows(ordered_rows)
        os.replace(temp_name, CSV_PATH)
    except Exception:
        try:
            os.unlink(temp_name)
        except FileNotFoundError:
            pass
        raise

    print(
        f"Updated {CSV_PATH.name}: {len(ordered_logins)} PR authors ordered; "
        f"{len(existing_rows)} existing score rows preserved."
    )


if __name__ == "__main__":
    try:
        sync_csv()
    except (OSError, urllib.error.URLError, ValueError, KeyError) as error:
        raise SystemExit(f"Could not sync participants: {error}") from error

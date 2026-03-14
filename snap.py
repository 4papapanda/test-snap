import os
import re
import json
import requests
from datetime import datetime
from urllib.parse import urlparse

PASTEBIN_URL = "https://pastebin.com/raw/AveJ8ejG"

TOKEN = os.getenv("GITHUB_TOKEN")

HEADERS = {}
if TOKEN:
    HEADERS["Authorization"] = f"Bearer {TOKEN}"

MAX_SIZE = 45 * 1024 * 1024
TODAY = datetime.utcnow().strftime("%Y-%m-%d")

report = {
    "repo_not_found": [],
    "drastically_changed": [],
    "skip": [],
    "null": [],
    "invalid": [],
    "http_errors": []
}

def fetch_url_list():

    r = requests.get(PASTEBIN_URL, timeout=60)

    if r.status_code != 200:
        raise Exception("Failed to download Pastebin list")

    return json.loads(r.text)


def api_get(url):
    return requests.get(url, headers=HEADERS, timeout=60)


def split_file(path):

    size = os.path.getsize(path)

    if size <= MAX_SIZE:
        return

    with open(path, "rb") as f:
        i = 0
        while True:
            chunk = f.read(MAX_SIZE)
            if not chunk:
                break

            with open(f"{path}.part{i}", "wb") as p:
                p.write(chunk)

            i += 1

    os.remove(path)


def download(url, dest):

    status, r = safe_request(url, stream=True)

    if status != 200 or r is None:
        code = status if status else "NETWORK_ERROR"
        report["http_errors"].append(f"{url} -> {code}")
        return False

    with open(dest, "wb") as f:
        for chunk in r.iter_content(8192):
            f.write(chunk)

    split_file(dest)

    return True


def detect_github_repo(url):

    m = re.match(r"https://github.com/([^/]+)/([^/]+)/?", url)

    if not m:
        return None

    return m.group(1), m.group(2)


def get_default_branch(owner, repo):

    api = f"https://api.github.com/repos/{owner}/{repo}"

    r = api_get(api)

    if r.status_code != 200:
        return None

    return r.json()["default_branch"]


def branch_exists(owner, repo, branch):

    api = f"https://api.github.com/repos/{owner}/{repo}/branches/{branch}"

    r = api_get(api)

    if r is None:
        return False

    return r.status_code == 200


def github_info(owner, repo):

    api = f"https://api.github.com/repos/{owner}/{repo}"

    r = api_get(api)

    if not r:
        return None

    data = r.json()

    commits_req = api_get(api + "/commits")

    if not commits_req:
        return None

    commits = commits_req.json()

    last_commit = commits[0]["commit"]["committer"]["date"]

    return {
        "date-updated": TODAY,
        "owner": data["owner"]["url"],
        "repository": data["url"],
        "last-commit": last_commit
    }


def save_info(path, info):

    with open(os.path.join(path, "info.json"), "w") as f:
        json.dump(info, f, indent=2)


def process_repo(owner, repo):

    base = f"{owner}/{repo}"

    os.makedirs(base, exist_ok=True)

    default = get_default_branch(owner, repo)

    if not default:
        report["repo_not_found"].append(f"{owner}/{repo}")
        return

    branches = [default]

    if branch_exists(owner, repo, "build"):
        branches.append("build")

    if branch_exists(owner, repo, "builds"):
        branches.append("builds")

    for b in branches:

        url = f"https://github.com/{owner}/{repo}/archive/refs/heads/{b}.tar.gz"

        dest = f"{base}/{b}.tar.gz"

        if not download(url, dest):
            report["invalid"].append(url)

    info = github_info(owner, repo)

    if info:
        save_info(base, info)


def process_archive(url):

    parsed = urlparse(url)

    # handle github archive URLs correctly
    m = re.match(r"https://github.com/([^/]+)/([^/]+)/archive/", url)

    if m:
        owner = m.group(1)
        repo = m.group(2)
    else:
        parts = parsed.path.strip("/").split("/")

        if len(parts) < 2:
            report["invalid"].append(url)
            return

        owner = parts[-3] if len(parts) >= 3 else "external"
        repo = parts[-2]

    base = f"{owner}/{repo}"

    os.makedirs(base, exist_ok=True)

    name = os.path.basename(parsed.path)

    dest = os.path.join(base, name)

    if not download(url, dest):
        return

    save_info(base, {
        "date-updated": TODAY,
        "owner": "",
        "repository": "",
        "last-commit": ""
    })


def safe_request(url, stream=False):
    try:
        r = requests.get(
            url,
            headers=HEADERS,
            stream=stream,
            timeout=120
        )
        return r.status_code, r
    except requests.exceptions.RequestException:
        return None, None


def api_get(url):

    status, r = safe_request(url)

    if status != 200 or r is None:
        code = status if status else "NETWORK_ERROR"
        report["http_errors"].append(f"{url} -> {code}")
        return None

    return r


def main():

    urls = fetch_url_list()

    for url in urls:

        if not url:
            report["null"].append(url)
            continue

        if url.endswith(".tar.gz") or url.endswith(".zip"):
            process_archive(url)
            continue

        repo = detect_github_repo(url)

        if repo:
            process_repo(*repo)
            continue

        report["skip"].append(url)


    with open("report.txt", "w") as f:

        f.write(f"Snapshot Report — {TODAY}\n\n")

        f.write("repo not found:\n")
        f.write("\n".join(report["repo_not_found"]))
        f.write("\n\n---\n\n")

        f.write("drastically changed:\n")
        f.write("\n".join(report["drastically_changed"]))
        f.write("\n\n---\n\n")

        f.write("skip entries:\n")
        f.write("\n".join(report["skip"]))
        f.write("\n\n---\n\n")

        f.write("null entries:\n")
        f.write("\n".join(map(str, report["null"])))
        f.write("\n\n---\n\n")

        f.write("invalid urls:\n")
        f.write("\n".join(report["invalid"]))
        f.write("\n\n---\n\n")

        f.write("http errors:\n")
        f.write("\n".join(report["http_errors"]))

if __name__ == "__main__":
    main()

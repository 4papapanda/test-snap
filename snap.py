import os
import re
import json
import subprocess
from datetime import datetime
from urllib.parse import urlparse

PASTEBIN_URL = "https://pastebin.com/raw/AveJ8ejG"
TOKEN = os.getenv("GITHUB_TOKEN")

MAX_SIZE = 45 * 1024 * 1024
TODAY = datetime.utcnow().strftime("%Y-%m-%d")

COMMON_HEADERS = [
    "User-Agent: Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/122 Safari/537.36",
    "Accept: */*",
    "Accept-Language: en-US,en;q=0.9",
    "Connection: keep-alive"
]

if TOKEN:
    COMMON_HEADERS.append(f"Authorization: Bearer {TOKEN}")

report = {
    "repo_not_found": [],
    "drastically_changed": [],
    "skip": [],
    "null": [],
    "invalid": [],
    "http_errors": []
}


def curl_get(url, output=None):

    cmd = ["curl", "-L", "--silent", "--show-error"]

    for h in COMMON_HEADERS:
        cmd += ["-H", h]

    if output:
        cmd += ["-o", output]

    cmd.append(url)

    result = subprocess.run(cmd, capture_output=True)

    return result.returncode, result.stdout


def fetch_url_list():

    code, data = curl_get(PASTEBIN_URL)

    if code != 0:
        raise Exception("Failed to download Pastebin list")

    return json.loads(data.decode())


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

    cmd = ["curl", "-L"]

    for h in COMMON_HEADERS:
        cmd += ["-H", h]

    cmd += ["-o", dest, url]

    r = subprocess.run(cmd)

    if r.returncode != 0:
        report["http_errors"].append(url)
        return False

    split_file(dest)

    return True


def detect_github_repo(url):

    m = re.match(r"https://github.com/([^/]+)/([^/]+)/?", url)

    if not m:
        return None

    return m.group(1), m.group(2)


def github_api(url):

    cmd = ["curl", "-L", "--silent"]

    for h in COMMON_HEADERS:
        cmd += ["-H", h]

    cmd.append(url)

    r = subprocess.run(cmd, capture_output=True)

    if r.returncode != 0:
        report["http_errors"].append(url)
        return None

    try:
        return json.loads(r.stdout.decode())
    except:
        return None


def get_default_branch(owner, repo):

    api = f"https://api.github.com/repos/{owner}/{repo}"

    data = github_api(api)

    if not data:
        return None

    return data.get("default_branch")


def branch_exists(owner, repo, branch):

    api = f"https://api.github.com/repos/{owner}/{repo}/branches/{branch}"

    data = github_api(api)

    return data is not None


def github_info(owner, repo):

    api = f"https://api.github.com/repos/{owner}/{repo}"

    data = github_api(api)

    if not data:
        return None

    commits = github_api(api + "/commits")

    if not commits:
        return None

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

    m = re.match(r"https://github.com/([^/]+)/([^/]+)/archive/", url)

    # ---- GITHUB ARCHIVE ----
    if m:

        owner = m.group(1)
        repo = m.group(2)

        base = f"{owner}/{repo}"

        os.makedirs(base, exist_ok=True)

        name = os.path.basename(parsed.path)

        dest = os.path.join(base, name)

        if not download(url, dest):
            return

        info = github_info(owner, repo)

        if info:
            save_info(base, info)

        return

    # ---- NON GITHUB ARCHIVE ----
    # download only, no info.json

    name = os.path.basename(parsed.path)

    base = "external"

    os.makedirs(base, exist_ok=True)

    dest = os.path.join(base, name)

    if not download(url, dest):
        report["invalid"].append(url)


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

        for k, v in report.items():
            f.write(f"{k}:\n")
            f.write("\n".join(map(str, v)))
            f.write("\n\n---\n\n")


if __name__ == "__main__":
    main()

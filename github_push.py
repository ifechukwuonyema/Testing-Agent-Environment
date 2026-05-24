import os
import subprocess
import urllib.request
import urllib.error
import json
import sys

REPO_NAME = "Testing-Agent-Environment"
REPO_DESC = "Kardit API testing harness — 8-microservice test suite with full project context for Claude Code"
REPO_DIR = os.path.dirname(os.path.abspath(__file__))

def run(cmd, cwd=None):
    result = subprocess.run(cmd, cwd=cwd or REPO_DIR, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"ERROR: {' '.join(cmd)}\n{result.stderr.strip()}")
        sys.exit(1)
    return result.stdout.strip()

def github_api(method, path, body=None):
    token = os.environ.get("GITHUB_TOKEN")
    if not token:
        print("ERROR: GITHUB_TOKEN environment variable not set.")
        print("Set it with:  $env:GITHUB_TOKEN = 'your_token_here'")
        sys.exit(1)

    url = f"https://api.github.com{path}"
    data = json.dumps(body).encode() if body else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Authorization", f"token {token}")
    req.add_header("Accept", "application/vnd.github+json")
    req.add_header("Content-Type", "application/json")

    try:
        with urllib.request.urlopen(req) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        body = e.read().decode()
        print(f"GitHub API error {e.code}: {body}")
        sys.exit(1)

print("1. Fetching GitHub username...")
user = github_api("GET", "/user")
username = user["login"]
print(f"   Authenticated as: {username}")

print("2. Creating repository...")
try:
    repo = github_api("POST", "/user/repos", {
        "name": REPO_NAME,
        "description": REPO_DESC,
        "private": False,
        "auto_init": False
    })
    clone_url = repo["clone_url"]
    print(f"   Created: {clone_url}")
except SystemExit:
    print("   Repo may already exist — checking...")
    repo = github_api("GET", f"/repos/{username}/{REPO_NAME}")
    clone_url = repo["clone_url"]
    print(f"   Found existing repo: {clone_url}")

auth_url = clone_url.replace("https://", f"https://{username}:{os.environ['GITHUB_TOKEN']}@")

print("3. Initialising git...")
if not os.path.exists(os.path.join(REPO_DIR, ".git")):
    run(["git", "init"])
else:
    print("   .git already exists, skipping init")

# Ensure we're on main branch
current_branch = subprocess.run(
    ["git", "rev-parse", "--abbrev-ref", "HEAD"],
    cwd=REPO_DIR, capture_output=True, text=True
).stdout.strip()
if current_branch != "main":
    has_commits = subprocess.run(
        ["git", "log", "--oneline", "-1"],
        cwd=REPO_DIR, capture_output=True, text=True
    ).returncode == 0
    if has_commits:
        run(["git", "branch", "-M", "main"])
    else:
        run(["git", "checkout", "-b", "main"])
print(f"   Branch: main")

print("4. Writing .gitignore...")
gitignore = os.path.join(REPO_DIR, ".gitignore")
if not os.path.exists(gitignore):
    with open(gitignore, "w") as f:
        f.write("__pycache__/\n*.pyc\n*.pyo\n.env\n*.log\ncopy_output.txt\ngithub_push.py\ncopy_memory.py\ncopy_memory_to_repo.bat\n")

print("5. Staging files...")
run(["git", "add", "."])

print("6. Committing...")
result = subprocess.run(
    ["git", "commit", "-m", "Initial commit: Kardit API test harness + full project context"],
    cwd=REPO_DIR, capture_output=True, text=True
)
if result.returncode != 0 and "nothing to commit" in result.stdout + result.stderr:
    print("   Nothing new to commit — will push existing HEAD")
elif result.returncode != 0:
    print(f"   Commit error: {result.stderr.strip()}")
    sys.exit(1)
else:
    print("   Committed.")

print("7. Setting remote...")
remotes = subprocess.run(["git", "remote"], cwd=REPO_DIR, capture_output=True, text=True).stdout.strip()
if "origin" in remotes.split():
    run(["git", "remote", "set-url", "origin", auth_url])
else:
    run(["git", "remote", "add", "origin", auth_url])

print("8. Pushing to GitHub...")
run(["git", "push", "-u", "origin", "main"])

print(f"\nDone! Repo live at: https://github.com/{username}/{REPO_NAME}")

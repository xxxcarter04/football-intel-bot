"""Push the bot to a private GitHub repo and create an always-on Render worker.

Required env vars:
  GITHUB_TOKEN          - GitHub PAT with repo (or fine-grained Contents:write) scope
  RENDER_API_KEY        - Render account API key
  FOOTBALL_DATA_TOKEN   - football-data.org API token
  TELEGRAM_BOT_TOKEN    - bot token from BotFather
Optional:
  GITHUB_REPO           - repo name (default: football-intel-bot)
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]


def required(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise SystemExit(f"Missing required env var: {name}")
    return value


def main() -> None:
    gh_token = required("GITHUB_TOKEN")
    render_key = required("RENDER_API_KEY")
    fd_token = required("FOOTBALL_DATA_TOKEN")
    tg_token = required("TELEGRAM_BOT_TOKEN")
    repo_name = os.environ.get("GITHUB_REPO", "football-intel-bot")

    gh = httpx.Client(
        headers={
            "Authorization": f"Bearer {gh_token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        },
        timeout=30,
    )
    user = gh.get("https://api.github.com/user")
    user.raise_for_status()
    login = user.json()["login"]
    print(f"GitHub user: {login}")

    repo_url = f"https://api.github.com/repos/{login}/{repo_name}"
    resp = gh.get(repo_url)
    if resp.status_code == 404:
        resp = gh.post(
            "https://api.github.com/user/repos",
            json={"name": repo_name, "private": True, "auto_init": False},
        )
        resp.raise_for_status()
        print(f"Created private repo: {login}/{repo_name}")
    else:
        resp.raise_for_status()
        print(f"Using existing repo: {login}/{repo_name}")

    def git(*args: str) -> None:
        subprocess.run(["git", *args], cwd=ROOT, check=True, capture_output=True)

    git("init", "-q", "-b", "main")
    git("config", "user.email", "bot@local")
    git("config", "user.name", "Football Intel Bot")
    git("add", "-A")
    subprocess.run(
        ["git", "commit", "-q", "-m", "Deploy football intel bot"],
        cwd=ROOT,
        check=False,
        capture_output=True,
    )
    remote = f"https://oauth2:{gh_token}@github.com/{login}/{repo_name}.git"
    subprocess.run(
        ["git", "remote", "remove", "origin"], cwd=ROOT, check=False, capture_output=True
    )
    git("remote", "add", "origin", remote)
    git("push", "-q", "-u", "origin", "main")
    print("Pushed code to GitHub")

    rh = httpx.Client(
        headers={"Authorization": f"Bearer {render_key}", "Accept": "application/json"},
        timeout=30,
    )
    owners = rh.get("https://api.render.com/v1/owners")
    owners.raise_for_status()
    owner_list = owners.json()
    if not owner_list:
        raise SystemExit("No Render owners found for that API key")
    owner_id = owner_list[0]["owner"]["id"]

    payload = {
        "type": "background_worker",
        "name": "football-intel-bot",
        "ownerId": owner_id,
        "repo": f"https://github.com/{login}/{repo_name}",
        "branch": "main",
        "autoDeployTrigger": "commit",
        "envVars": [
            {"key": "TELEGRAM_BOT_TOKEN", "value": tg_token},
            {"key": "FOOTBALL_DATA_TOKEN", "value": fd_token},
            {"key": "API_FOOTBALL_KEY", "value": os.environ.get("API_FOOTBALL_KEY", "")},
            {"key": "API_FOOTBALL_HOST", "value": "api-football-v1.p.rapidapi.com"},
            {"key": "HISTORY_SEASONS", "value": "2"},
            {"key": "CACHE_TTL_HOURS", "value": "6"},
            {"key": "LEAGUE_IDS", "value": "39,140,135,78,61,2"},
            {"key": "TIMEZONE", "value": "UTC"},
            {"key": "DIGEST_TIME", "value": "09:00"},
        ],
        "serviceDetails": {
            "runtime": "docker",
            "plan": "0.5c-512mb",
            "region": "oregon",
            "envSpecificDetails": {
                "dockerfilePath": "./Dockerfile",
                "dockerCommand": "python -m football_intel.bot.main",
            },
        },
    }
    result = rh.post("https://api.render.com/v1/services", json=payload)
    if result.status_code >= 400:
        print("Render service creation failed:", result.status_code, result.text[:1500])
        sys.exit(1)
    data = result.json()
    print("Render worker created:", data.get("id"), data.get("name"))
    print("The bot will be live in a few minutes once the image builds.")


if __name__ == "__main__":
    main()

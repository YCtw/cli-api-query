# Github Client to search repositories - Request to Github API
import requests
import os


def search_repositories(params):
    url = "https://api.github.com/search/repositories"

    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "nl-to-github-cli",
    }

    Productuib ebvironment token needs to used here
    token = os.getenv("GITHUB_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    print("the Github API request params are:", params)
    response = requests.get(url, headers=headers, params=params)
    return response.json()

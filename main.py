import sys
from agent import run_agent
from query_builder import build_github_params
from github_client import search_repositories


def main():
    # Check command line arguments
    if len(sys.argv) < 2:
        # Invalid user input for this tool
        print('Usage: python main.py "top python repos"')
        return

    user_input = sys.argv[1]

    # Main process: Run the agent to parse the user input and return the structured query
    parsed = run_agent(user_input) #LLM Handler to request the LLM API calls and check the output (safe parse json)
    params = build_github_params(parsed) #From LLM output, Query Builder to build the Github API parameters
    result = search_repositories(params) # Request to Github API

    # Prin the first 5 repositories for reference as references
    for repo in result.get("items", [])[:5]:
        print(repo["full_name"], repo["stargazers_count"])



if __name__ == "__main__":
    main()

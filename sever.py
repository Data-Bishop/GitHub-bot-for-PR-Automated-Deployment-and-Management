import os
import subprocess
import hmac
import hashlib
from flask import Flask, request, abort
from github import Github, GithubIntegration
from dotenv import load_dotenv

app = Flask(__name__)

# Load environment variables
load_dotenv()

GITHUB_APP_ID = os.getenv('GITHUB_APP_ID')
GITHUB_PRIVATE_KEY = os.getenv('GITHUB_PRIVATE_KEY')
GITHUB_WEBHOOK_SECRET = os.getenv('GITHUB_WEBHOOK_SECRET')
DEPLOYMENT_URL = os.getenv('DEPLOYMENT_URL')

github_integration = GithubIntegration(GITHUB_APP_ID, GITHUB_PRIVATE_KEY)

def verify_signature(payload, signature):
    secret = bytes(GITHUB_WEBHOOK_SECRET, 'utf-8')
    mac = hmac.new(secret, payload, hashlib.sha256).hexdigest()
    return hmac.compare_digest(f'sha256={mac}', signature)

@app.route('/webhook', methods=['POST'])
def webhook():
    payload = request.get_data()
    signature = request.headers.get('X-Hub-Signature-256')
    if not verify_signature(payload, signature):
        abort(400, 'Invalid signature')
    
    data = request.json

    if 'action' not in data:
        return '', 400

    action = data['action']
    pull_request = data.get('pull_request')
    repository = data.get('repository')

    if not pull_request or not repository:
        return '', 400

    if action in ["opened", "synchronize"]:
        handle_opened_pr(pull_request, repository)
    elif action == "closed":
        handle_closed_pr(pull_request, repository)

    return '', 200

def handle_opened_pr(pull_request, repository):
    branch = pull_request['head']['ref']
    repo_name = repository['name']
    owner = repository['owner']['login']

    repo_url = f"https://github.com/{owner}/{repo_name}.git"
    repo_path = f"./{repo_name}"

    # Get installation access token
    installation_id = repository['installation']['id']
    access_token = github_integration.get_access_token(installation_id).token

    # Authenticate to GitHub
    g = Github(access_token)

    # Clone the repository and check out the branch
    subprocess.run(["git", "clone", repo_url])
    subprocess.run(["git", "checkout", branch], cwd=repo_path)

    # Deploy the application using Docker Compose
    subprocess.run(["docker-compose", "up", "-d"], cwd=repo_path)

    # Comment on the pull request
    repo = g.get_repo(f"{owner}/{repo_name}")
    issue = repo.get_issue(number=pull_request['number'])
    issue.create_comment("Deployment started.")

    url = f"{DEPLOYMENT_URL}/{branch}"
    issue.create_comment(f"Deployment complete. Access the application at {url}.")

def handle_closed_pr(pull_request, repository):
    branch = pull_request['head']['ref']
    repo_name = repository['name']
    repo_path = f"./{repo_name}"

    # Clean up Docker resources
    subprocess.run(["docker-compose", "down", "-v", "--rmi", "all", "--remove-orphans"], cwd=repo_path)

    # Remove the cloned repository
    subprocess.run(["rm", "-rf", repo_path])

if __name__ == '__main__':
    app.run(port=3000)

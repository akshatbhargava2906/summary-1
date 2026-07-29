import os
import time
import requests
from requests.auth import HTTPBasicAuth
from dotenv import load_dotenv

load_dotenv()

BASE_URL = os.getenv("AI_CORE_BASE_URL", "").rstrip("/")
AUTH_URL = os.getenv("AI_CORE_AUTH_URL", "")
CLIENT_ID = os.getenv("AI_CORE_CLIENT_ID", "")
CLIENT_SECRET = os.getenv("AI_CORE_CLIENT_SECRET", "")
RESOURCE_GROUP = os.getenv("AI_CORE_RESOURCE_GROUP", "default")
DEPLOYMENT_ID = os.getenv("AI_CORE_DEPLOYMENT_ID", "")
EMBEDDING_ID = os.getenv("AI_CORE_EMBEDDING_ID", "")

AZ_ENDPOINT = os.getenv("AZURE_EMBEDDING_ENDPOINT", "").rstrip("/")
AZ_API_KEY = os.getenv("AZURE_EMBEDDING_API_KEY", "")
AZ_DEPLOYMENT = os.getenv("AZURE_EMBEDDING_DEPLOYMENT", "")
AZ_API_VERSION = os.getenv("AZURE_EMBEDDING_API_VERSION", "2024-02-01")

def test_env():
    print("\n 1. ENV VARIABLES ")
    required = {
        "AI_CORE_BASE_URL": BASE_URL,
        "AI_CORE_AUTH_URL": AUTH_URL,
        "AI_CORE_CLIENT_ID": CLIENT_ID,
        "AI_CORE_CLIENT_SECRET": CLIENT_SECRET,
        "AI_CORE_DEPLOYMENT_ID": DEPLOYMENT_ID,
        "AI_CORE_EMBEDDING_ID": EMBEDDING_ID,
    }
    all_ok = True
    for key, val in required.items():
        status = "OK" if val else "MISSING"
        print(f"  {status}  {key}")
        if not val:
            all_ok = False
    return all_ok


def test_token():
    print("\n 2. TOKEN FETCH ")
    try:
        resp = requests.post(
            AUTH_URL,
            auth=HTTPBasicAuth(CLIENT_ID, CLIENT_SECRET),
            data={"grant_type": "client_credentials"},
            verify=False,
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()
        token = data["access_token"]
        expires = data.get("expires_in", "?")
        print(f"  OK  Token received  (expires_in: {expires}s)")
        print(f"      Token prefix: {token[:20]}...")
        return token
    except Exception as e:
        print(f"  FAIL  {e}")
        return None


def test_claude(token: str):
    print("\n 3. CLAUDE INVOKE ")
    url = f"{BASE_URL}/v2/inference/deployments/{DEPLOYMENT_ID}/invoke"
    headers = {
        "Authorization": f"Bearer {token}",
        "AI-Resource-Group": RESOURCE_GROUP,
        "Content-Type": "application/json",
    }
    body = {
        "anthropic_version": "bedrock-2023-05-31",
        "max_tokens": 64,
        "messages": [{"role": "user", "content": "Reply with exactly: CLAUDE_OK"}],
    }
    try:
        start = time.time()
        resp = requests.post(url, headers=headers, json=body, verify=False, timeout=60)
        elapsed = round(time.time() - start, 2)
        resp.raise_for_status()
        reply = resp.json()["content"][0]["text"].strip()
        print(f"  OK  Response in {elapsed}s")
        print(f"      Reply: {reply}")
    except Exception as e:
        print(f"  FAIL  {e}")
        if hasattr(e, "response") and e.response is not None:
            print(f"      Status: {e.response.status_code}")
            print(f"      Body:   {e.response.text[:300]}")


def test_azure_embedding():
    print("\n 4. AZURE EMBEDDING ")
    url = (
        f"{AZ_ENDPOINT}/openai/deployments/{AZ_DEPLOYMENT}"
        f"/embeddings?api-version={AZ_API_VERSION}"
    )
    headers = {"api-key": AZ_API_KEY, "Content-Type": "application/json"}
    try:
        start = time.time()
        resp = requests.post(url, headers=headers, json={"input": "Hemoglobin level is low."}, verify=False, timeout=30)
        elapsed = round(time.time() - start, 2)
        resp.raise_for_status()
        vec = resp.json()["data"][0]["embedding"]
        print(f"  OK  Response in {elapsed}s")
        print(f"      Dimensions: {len(vec)}")
        print(f"      First 5:    {vec[:5]}")
    except Exception as e:
        print(f"  FAIL  {e}")


if __name__ == "__main__":
    print("  AI Core Connection Test")

    if not test_env():
        print("\nFix missing env variables in .env before continuing.")
        exit(1)

    token = test_token()
    if not token:
        print("\nCannot proceed without a valid token.")
        exit(1)

    test_claude(token)
    test_azure_embedding()
    print("  Done")
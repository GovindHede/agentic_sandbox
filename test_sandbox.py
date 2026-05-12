"""End-to-end test: sends agent code to the sandbox API and prints the result."""
import requests
import json

API_URL = "http://127.0.0.1:8000/api/v1/sandbox/run"

# This is the untrusted agent code that will run INSIDE the Docker container.
# It tries to call Stripe — the proxy will intercept it and return a fake response.
agent_code = """
import urllib.request
resp = urllib.request.urlopen('http://api.stripe.com/v1/charges')
print(resp.read().decode())
"""

print("Sending agent code to sandbox...")
response = requests.post(API_URL, json={"code": agent_code})

print(f"\nHTTP Status Code: {response.status_code}")

if response.status_code != 200:
    print(f"ERROR: {response.text}")
else:
    result = response.json()
    print(f"Status: {result.get('status')}")
    print(f"Execution Time: {result.get('execution_time', 0):.2f}s")
    print(f"\n--- STDOUT ---\n{result.get('stdout', '')}")
    print(f"--- STDERR ---\n{result.get('stderr', '')}")

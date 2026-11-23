"""Get a cTrader Open API access token for your Pepperstone account (one-time setup).

Usage (on your own computer, or in a GitHub Codespace):
    pip install ctrader-open-api
    python scripts/get_ctrader_token.py

It prints a link. Open it, log in with your Pepperstone cTrader ID, approve read-only access,
and you'll be redirected to a page whose address contains ?code=... . Paste that whole address back here.
"""
import urllib.parse

from ctrader_open_api import Auth

client_id = input("cTrader app Client ID: ").strip()
client_secret = input("cTrader app Secret: ").strip()
redirect = input("Redirect URI you registered on the app [http://localhost]: ").strip() or "http://localhost"

auth = Auth(client_id, client_secret, redirect)
print("\n1) Open this link and approve access:\n")
print(auth.getAuthUri(scope="accounts"))  # read-only: the agent never trades
pasted = input("\n2) Paste the full address you were redirected to (or just the code): ").strip()
code = urllib.parse.parse_qs(urllib.parse.urlparse(pasted).query).get("code", [pasted])[0]

tok = auth.getToken(code)
if not tok or not tok.get("accessToken"):
    raise SystemExit(f"Failed: {tok}")

print("\nAdd these as GitHub repository secrets (Settings -> Secrets and variables -> Actions):\n")
print(f"CTRADER_CLIENT_ID      = {client_id}")
print(f"CTRADER_CLIENT_SECRET  = {client_secret}")
print(f"CTRADER_ACCESS_TOKEN   = {tok['accessToken']}")
print(f"CTRADER_REFRESH_TOKEN  = {tok.get('refreshToken', '')}")
print(f"\nAccess token lasts about {int(tok.get('expiresIn', 0)) // 86400} days.")

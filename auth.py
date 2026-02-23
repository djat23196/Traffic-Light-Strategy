#!/usr/bin/env python3
"""
Fyers Authentication Manager
==============================
Handles the complete OAuth2 authentication flow for Fyers API v3.

This module:
- Opens your browser for Fyers login
- Saves your access token locally so you don't login every time
- Auto-refreshes expired tokens
- Provides a ready-to-use Fyers API instance

Usage:
    from auth import get_fyers
    fyers = get_fyers()  # Returns authenticated Fyers instance
"""

import os
import json
import time
import logging
import webbrowser
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
from datetime import datetime
from pathlib import Path
from typing import Optional
from fyers_apiv3 import fyersModel

logger = logging.getLogger(__name__)

# Directory to store tokens (inside this project folder)
TOKEN_DIR = Path(__file__).parent / ".tokens"
TOKEN_FILE = TOKEN_DIR / "access_token.json"


class FyersAuth:
    """
    Complete Fyers authentication handler.

    First-time setup:
    1. Opens browser → you login to Fyers
    2. Fyers redirects to your redirect_uri with an auth code in the URL
    3. You paste that auth code back here
    4. Token is saved locally for future sessions (valid ~24 hours)

    Subsequent runs:
    - Automatically loads saved token
    - Refreshes if expired
    - Only asks for login again if refresh fails
    """

    def __init__(self, client_id: str, secret_key: str, redirect_uri: str):
        self.client_id = client_id
        self.secret_key = secret_key
        self.redirect_uri = redirect_uri
        self.token_info = None
        self.fyers = None

        # Create token storage directory
        TOKEN_DIR.mkdir(exist_ok=True)

    def _save_token(self):
        """Save token to disk for reuse across sessions"""
        if self.token_info:
            with open(TOKEN_FILE, 'w') as f:
                json.dump(self.token_info, f, indent=2)
            logger.info("Token saved to disk")

    def _load_token(self) -> bool:
        """Load previously saved token from disk"""
        if not TOKEN_FILE.exists():
            return False
        try:
            with open(TOKEN_FILE, 'r') as f:
                self.token_info = json.load(f)
            if 'access_token' in self.token_info:
                logger.info("Loaded saved token from disk")
                return True
        except (json.JSONDecodeError, KeyError):
            pass
        return False

    def _is_token_valid(self) -> bool:
        """Check if the current token is still valid"""
        if not self.token_info or 'access_token' not in self.token_info:
            return False
        # If we have an expiry timestamp, check it (with 5-min buffer)
        if 'exp' in self.token_info:
            return int(time.time()) < (self.token_info['exp'] - 300)
        return True

    def _do_login(self) -> bool:
        """
        Run the full OAuth2 login flow with auto-capture.
        Starts a local HTTP server → opens browser → captures auth code automatically.
        Falls back to manual paste if localhost redirect is not configured.
        """
        try:
            session = fyersModel.SessionModel(
                client_id=self.client_id,
                redirect_uri=self.redirect_uri,
                response_type="code",
                state="sample_state",
                secret_key=self.secret_key,
                grant_type="authorization_code"
            )

            auth_url = session.generate_authcode()

            # Try auto-capture if redirect_uri points to localhost
            parsed = urlparse(self.redirect_uri)
            is_localhost = parsed.hostname in ("localhost", "127.0.0.1")

            if is_localhost:
                port = parsed.port or 8080
                auth_code = self._auto_capture_auth_code(auth_url, port)
            else:
                auth_code = self._manual_capture_auth_code(auth_url)

            if not auth_code:
                print("  Could not get auth code.")
                return False

            session.set_token(auth_code)
            response = session.generate_token()

            if 'access_token' in response:
                self.token_info = response
                self._save_token()
                print("\n  Login successful!\n")
                return True
            else:
                print(f"\n  Login failed: {response}")
                return False

        except Exception as e:
            logger.error(f"Login error: {e}")
            return False

    def _auto_capture_auth_code(self, auth_url: str, port: int) -> Optional[str]:
        """Start local server, open browser, auto-capture the auth code from redirect."""
        captured = {"code": None}

        class CallbackHandler(BaseHTTPRequestHandler):
            def do_GET(self):
                params = parse_qs(urlparse(self.path).query)
                code = params.get("auth_code", params.get("code", [None]))[0]
                captured["code"] = code
                self.send_response(200)
                self.send_header("Content-Type", "text/html")
                self.end_headers()
                self.wfile.write(b"""<html><body style="font-family:sans-serif;text-align:center;padding:60px">
                    <h2>Login Successful!</h2>
                    <p>You can close this tab and return to the terminal.</p>
                    <script>setTimeout(()=>window.close(),2000)</script>
                    </body></html>""")

            def log_message(self, format, *args):
                pass  # Suppress server logs

        server = HTTPServer(("127.0.0.1", port), CallbackHandler)
        server.timeout = 120  # 2 min timeout

        print("\n" + "=" * 60)
        print("  FYERS LOGIN (Auto-Capture)")
        print("=" * 60)
        print()
        print("  Browser will open. Just login & approve.")
        print("  Auth code will be captured automatically!")
        print(f"  Listening on http://127.0.0.1:{port}")
        print()
        print("=" * 60)

        webbrowser.open(auth_url, new=1)

        # Wait for the callback
        while captured["code"] is None:
            server.handle_request()
            if captured["code"] is not None:
                break

        server.server_close()
        if captured["code"]:
            print("  Auth code captured automatically!")
        return captured["code"]

    def _manual_capture_auth_code(self, auth_url: str) -> Optional[str]:
        """Fallback: ask user to paste the redirect URL manually."""
        print("\n" + "=" * 60)
        print("  FYERS LOGIN REQUIRED")
        print("=" * 60)
        print()
        print("  A browser window will open. Please:")
        print("  1. Login to your Fyers account")
        print("  2. Approve the app permissions")
        print("  3. You'll be redirected — copy the FULL URL")
        print("  4. Paste it below")
        print()
        print(f"  If the browser doesn't open, go to:")
        print(f"  {auth_url}")
        print()
        print("  TIP: Set REDIRECT_URI to http://127.0.0.1:8080")
        print("       in config.py & Fyers dashboard for auto-capture!")
        print()
        print("=" * 60)

        webbrowser.open(auth_url, new=1)
        redirect_url = input("\n  Paste the full redirect URL here: ").strip()

        if "auth_code=" in redirect_url:
            return redirect_url.split("auth_code=")[1].split("&")[0]
        elif "code=" in redirect_url:
            return redirect_url.split("code=")[1].split("&")[0]
        return redirect_url or None

    def _try_refresh(self) -> bool:
        """Try to refresh an expired token"""
        if not self.token_info or 'refresh_token' not in self.token_info:
            return False
        try:
            session = fyersModel.SessionModel(
                client_id=self.client_id,
                redirect_uri=self.redirect_uri,
                response_type="code",
                state="sample_state",
                secret_key=self.secret_key,
                grant_type="refresh_token"
            )
            session.set_token(self.token_info['refresh_token'])
            response = session.generate_token()

            if 'access_token' in response:
                self.token_info = response
                self._save_token()
                logger.info("Token refreshed successfully")
                return True
        except Exception as e:
            logger.error(f"Token refresh failed: {e}")
        return False

    def get_fyers(self) -> Optional[fyersModel.FyersModel]:
        """
        Get an authenticated Fyers API instance.
        Handles the full auth flow automatically.

        Returns:
            fyersModel.FyersModel ready to use, or None if auth fails
        """
        # Step 1: Try loading saved token
        if self._load_token():
            if self._is_token_valid():
                logger.info("Using saved valid token")
            else:
                logger.info("Token expired, attempting refresh...")
                if not self._try_refresh():
                    logger.info("Refresh failed, need fresh login")
                    if not self._do_login():
                        return None
        else:
            # No saved token — need fresh login
            if not self._do_login():
                return None

        # Step 2: Create Fyers instance
        if self.token_info and 'access_token' in self.token_info:
            self.fyers = fyersModel.FyersModel(
                token=self.token_info['access_token'],
                is_async=False,
                client_id=self.client_id
            )
            return self.fyers

        return None

    def test_connection(self) -> bool:
        """Quick test to verify the connection works"""
        if not self.fyers:
            return False
        try:
            response = self.fyers.quotes(data={"symbols": "NSE:NIFTY50-INDEX"})
            if response.get('s') == 'ok':
                ltp = response['d'][0]['v']['lp']
                print(f"  Connection OK! NIFTY50 LTP: {ltp}")
                return True
        except Exception as e:
            print(f"  Connection test failed: {e}")
        return False

    def clear_tokens(self):
        """Clear saved tokens (forces fresh login next time)"""
        if TOKEN_FILE.exists():
            TOKEN_FILE.unlink()
            print("  Saved tokens cleared. You'll need to login again next time.")


# ─── Convenience Function ────────────────────────────────────────────────────

def get_fyers():
    """
    Quick way to get an authenticated Fyers instance.

    Usage:
        from auth import get_fyers
        fyers = get_fyers()
        print(fyers.quotes(data={"symbols": "NSE:NIFTY50-INDEX"}))
    """
    from config import CLIENT_ID, CLIENT_SECRET, REDIRECT_URI

    if CLIENT_ID == "XXXXXXXXXX-100":
        print("\n" + "=" * 60)
        print("  SETUP REQUIRED")
        print("=" * 60)
        print()
        print("  You haven't configured your Fyers credentials yet!")
        print("  Open config.py and replace the placeholder values:")
        print()
        print("    CLIENT_ID = \"YOUR_APP_ID-100\"")
        print("    CLIENT_SECRET = \"YOUR_SECRET_KEY\"")
        print()
        print("  Get these from: https://myapi.fyers.in/dashboard")
        print("=" * 60 + "\n")
        return None

    auth = FyersAuth(CLIENT_ID, CLIENT_SECRET, REDIRECT_URI)
    return auth.get_fyers()


if __name__ == "__main__":
    """Test authentication when run directly"""
    print("\n  Testing Fyers Authentication...\n")
    fyers = get_fyers()
    if fyers:
        from config import CLIENT_ID, CLIENT_SECRET, REDIRECT_URI
        auth = FyersAuth(CLIENT_ID, CLIENT_SECRET, REDIRECT_URI)
        auth.fyers = fyers
        auth.test_connection()
    else:
        print("  Authentication failed. Check your config.py credentials.")

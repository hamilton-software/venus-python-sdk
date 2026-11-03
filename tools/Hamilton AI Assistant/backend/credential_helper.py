"""The engine's apiKeyHelper for the company sign-in: prints the current access token and nothing else.

The agent engine runs this command whenever it needs a credential (and again when its cache of the
answer runs out), so a conversation that outlives one token keeps working: the app refreshes the
token, this script just asks the app for the current one on this PC (127.0.0.1) with the secret the
app made for this launch. Standard library only, because the engine starts it as a separate process.
"""

from __future__ import annotations

import os
import sys
import urllib.error
import urllib.request

URL_ENV = "HAMILTON_AI_ASSISTANT_HELPER_URL"
SECRET_ENV = "HAMILTON_AI_ASSISTANT_HELPER_SECRET"
SECRET_HEADER = "X-Hamilton-Helper-Secret"


def main() -> int:
    url, secret = os.environ.get(URL_ENV, ""), os.environ.get(SECRET_ENV, "")
    if not url or not secret:
        sys.stderr.write("The Hamilton AI Assistant did not give this helper its address.\n")
        return 1
    request = urllib.request.Request(url, headers={SECRET_HEADER: secret})
    try:
        with urllib.request.urlopen(request, timeout=30) as response:  # noqa: S310 - the app's own loopback address
            token = response.read().decode("utf-8").strip()
    except urllib.error.HTTPError as exc:
        sys.stderr.write(f"The Hamilton AI Assistant could not give a token: {exc.read().decode('utf-8', 'replace')[:200]}\n")
        return 1
    except (urllib.error.URLError, OSError) as exc:
        sys.stderr.write(f"The Hamilton AI Assistant is not reachable: {exc}\n")
        return 1
    if not token:
        return 1
    sys.stdout.write(token)
    return 0


if __name__ == "__main__":
    sys.exit(main())

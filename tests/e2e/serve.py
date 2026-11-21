"""Run the app against the local test database for the browser tests.

    python -m tests.e2e.serve 8765
"""
import sys

from tests import testenv

testenv.configure(force_database=True)

import uvicorn  # noqa: E402

import app  # noqa: E402

# Browser tests log in many times; the 5-a-minute limits would block them.
app.limiter.enabled = False

if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8765
    uvicorn.run(app.app, host="127.0.0.1", port=port, log_level="warning")

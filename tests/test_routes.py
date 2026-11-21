"""BE1-2: every (method, path) the app serves, compared to a golden file.

The refactor moves all routes out of app.py. This test fails if any route
is dropped, renamed, gains or loses a trailing slash, or changes method.

After an intended route change, regenerate the golden file with:
    UPDATE_GOLDEN=1 pytest tests/test_routes.py
and review the diff of tests/golden/routes.txt.
"""
from pathlib import Path

from fastapi.routing import APIRoute
from starlette.routing import Mount

from tests.conftest import update_golden

GOLDEN = Path(__file__).parent / "golden" / "routes.txt"


def collect_routes() -> list[str]:
    import app as app_module

    lines = set()
    for route in app_module.app.routes:
        if isinstance(route, APIRoute):
            for method in route.methods:
                lines.add(f"{method} {route.path}")
        elif isinstance(route, Mount):
            lines.add(f"MOUNT {route.path}")
    return sorted(lines)


def test_routes_match_golden():
    actual = collect_routes()
    if update_golden():
        GOLDEN.write_text("\n".join(actual) + "\n")
    expected = GOLDEN.read_text().splitlines()

    missing = sorted(set(expected) - set(actual))
    added = sorted(set(actual) - set(expected))
    assert not missing and not added, (
        "Routes differ from tests/golden/routes.txt.\n"
        f"Missing (in golden, not in app): {missing}\n"
        f"Added (in app, not in golden): {added}\n"
        "If this change is intended, run UPDATE_GOLDEN=1 pytest tests/test_routes.py"
    )

"""Pre-renders the public pages to static HTML for a CDN.

Why this exists: on a free tier the app container sleeps, and the first visitor
pays a 30-60 second cold start. That is almost entirely container scheduling -
this app itself imports in about 280ms - so it cannot be optimised away in code.

The fix is to stop the visitor waiting on it at all. The landing and guide pages
carry no user data, so they can be served instantly from a CDN. They ping the
API on load, which wakes the container while the visitor is still reading. By
the time anyone clicks "Sign in", the backend is warm.

    python tools/export_static.py --api https://podium.onrender.com
    # then deploy dist/ to Cloudflare Pages, Netlify, or GitHub Pages
"""
import argparse
import re
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

PAGES = {"/": "index.html", "/guide": "guide.html"}

# Anything that needs a signed-in session has to go to the real backend.
DYNAMIC_PREFIXES = ("/signin", "/auth", "/practise", "/parent", "/children",
                    "/topic", "/consent", "/speak", "/prep", "/feedback", "/signout")

WARMUP = """
<script>
/* Wake the API while the visitor reads, so a sleeping free-tier container has
   finished starting by the time they click through. Fire and forget: a failure
   here must never affect the page. */
(function () {
  var api = %s;
  if (!api) return;
  var done = false;
  function warm() {
    if (done) return;
    done = true;
    try { fetch(api + "/health", { mode: "no-cors", cache: "no-store" }); } catch (e) {}
  }
  warm();
  /* Try again when they show intent, in case the first ping was too early. */
  document.addEventListener("pointerdown", warm, { once: true, passive: true });
})();
</script>
"""


def rewrite(html: str, api: str) -> str:
    """Point dynamic links at the backend; keep static assets local."""
    def fix(match: re.Match) -> str:
        attr, url = match.group(1), match.group(2)
        if url.startswith(DYNAMIC_PREFIXES):
            return f'{attr}="{api.rstrip("/")}{url}"'
        if url.startswith("/static/"):
            return f'{attr}=".{url}"'
        if url == "/":
            return f'{attr}="./index.html"'
        if url == "/guide":
            return f'{attr}="./guide.html"'
        return match.group(0)

    html = re.sub(r'(href|src|action)="(/[^"]*)"', fix, html)
    return html.replace("</body>", WARMUP % f'"{api.rstrip("/")}"' + "</body>")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api", required=True, help="Base URL of the deployed backend")
    parser.add_argument("--out", default="dist", help="Output directory (default: dist)")
    args = parser.parse_args()

    from fastapi.testclient import TestClient
    import main as app_module

    out = ROOT / args.out
    if out.exists():
        shutil.rmtree(out)
    (out / "static").mkdir(parents=True)

    with TestClient(app_module.app) as client:
        for route, filename in PAGES.items():
            response = client.get(route, follow_redirects=False)
            if response.status_code != 200:
                raise SystemExit(f"{route} returned {response.status_code}, expected 200")
            (out / filename).write_text(rewrite(response.text, args.api), encoding="utf-8")
            print(f"  {route:8} -> {filename}  ({len(response.text) // 1024} KB)")

    for asset in (ROOT / "static").glob("*"):
        if asset.is_file() and not asset.name.startswith("_"):
            shutil.copy2(asset, out / "static" / asset.name)
    print(f"  copied {len(list((out / 'static').glob('*')))} static assets")
    print(f"\nDeploy {out.relative_to(ROOT)}/ to any CDN. Dynamic links point at {args.api}")


if __name__ == "__main__":
    main()

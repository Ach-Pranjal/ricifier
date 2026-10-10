import sys
import urllib.request
from html.parser import HTMLParser

SKIP = ("script", "style", "nav", "footer")


class TextOnly(HTMLParser):
    """Collects only the visible text of a web page."""

    def __init__(self):
        super().__init__()
        self.parts = []
        self.skip = 0

    def handle_starttag(self, tag, attrs):
        if tag in SKIP:
            self.skip += 1

    def handle_endtag(self, tag):
        if tag in SKIP and self.skip:
            self.skip -= 1

    def handle_data(self, data):
        if not self.skip and data.strip():
            self.parts.append(data.strip())


def fetch_text(url):
    """Download a page and return its text without the HTML."""
    req = urllib.request.Request(url, headers={"User-Agent": "Ricifier"})
    html = urllib.request.urlopen(req, timeout=20).read().decode("utf-8", errors="replace")
    parser = TextOnly()
    parser.feed(html)
    return "\n".join(parser.parts)


if __name__ == "__main__":
    text = fetch_text(sys.argv[1])
    print("characters:", len(text))
    print("about tokens:", len(text) // 4)
    print(text[:600])

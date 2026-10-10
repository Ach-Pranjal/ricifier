from fetch_docs import fetch_text

LOCAL_DOCS = "file:///usr/share/doc/kitty/html/conf.html"
ONLINE_DOCS = "https://sw.kovidgoyal.net/kitty/conf/"

# the only settings Gemma will be asked about
SAFE_SETTINGS = [
    "background", "foreground", "cursor",
    "selection_background", "selection_foreground",
    "url_color", "active_border_color", "inactive_border_color",
    "background_opacity", "window_padding_width", "cursor_shape",
]


def get_docs(url=None):
    """Use the given url if there is one, else the local copy, else the official website."""
    if url:
        return fetch_text(url)
    try:
        return fetch_text(LOCAL_DOCS)
    except OSError:
        return fetch_text(ONLINE_DOCS)


def clip(text, name, max_chars=1500):
    """Cut out the part of the docs page that describes one setting."""
    lines = text.split("\n")
    for i, line in enumerate(lines):
        # a setting's heading looks like: name, then within 3 lines a "¶"
        if line == name and "¶" in lines[i + 1:i + 4]:
            part = lines[i:i + 40]
            marks = [j for j, x in enumerate(part) if x == "¶"]
            if len(marks) > 1:               # stop where the next setting starts
                part = part[:marks[1]]
            return "\n".join(part)[:max_chars]
    return None


if __name__ == "__main__":
    docs = get_docs()
    for name in ["background", "background_opacity"]:
        print("=====", name)
        print(clip(docs, name))

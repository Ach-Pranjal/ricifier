import numpy as np
from PIL import Image

def _to_oklab(rgb):
    """Convert (N,3) sRGB values in 0-1 to OKLab, where distance matches human perception."""
    c = np.where(rgb <= 0.04045, rgb / 12.92, ((rgb + 0.055) / 1.055) ** 2.4)
    r, g, b = c[:, 0], c[:, 1], c[:, 2]
    l = np.cbrt(0.4122214708 * r + 0.5363325363 * g + 0.0514459929 * b)
    m = np.cbrt(0.2119034982 * r + 0.6806995451 * g + 0.1073969566 * b)
    s = np.cbrt(0.0883024619 * r + 0.2817188376 * g + 0.6299787005 * b)
    return np.stack([
        0.2104542553 * l + 0.7936177850 * m - 0.0040720468 * s,
        1.9779984951 * l - 2.4285922050 * m + 0.4505937099 * s,
        0.0259040371 * l + 0.7827717662 * m - 0.8086757660 * s,
    ], axis=1)


def extract_palette(image_path, n=8, k=24):
    """Return n distinct, representative colors as hex strings."""
    img = Image.open(image_path).convert("RGB")
    img.thumbnail((128, 128))
    px = np.asarray(img, dtype=np.float32).reshape(-1, 3) / 255
    lab = _to_oklab(px)

    # k-means: group similar pixels into k clusters
    rng = np.random.default_rng(0)
    centers = lab[rng.choice(len(lab), k, replace=False)]
    for _ in range(15):
        dist = ((lab[:, None, :] - centers[None, :, :]) ** 2).sum(axis=2)
        labels = dist.argmin(axis=1)
        for i in range(k):
            members = lab[labels == i]
            if len(members):
                centers[i] = members.mean(axis=0)

    # score each cluster: size matters, but vivid colors get a boost
    clusters = []
    for i in range(k):
        mask = labels == i
        if not mask.any():
            continue
        share = mask.mean()
        chroma = float(np.hypot(centers[i][1], centers[i][2]))
        score = (share ** 0.5) * (0.3 + chroma * 5)
        rgb = (px[mask].mean(axis=0) * 255).round().astype(int)
        clusters.append((score, centers[i], "#%02x%02x%02x" % tuple(rgb)))
    clusters.sort(key=lambda c: c[0], reverse=True)

    # pick the best, skipping colors too close to one already chosen
    picked = []
    for score, center, hex_color in clusters:
        if all(np.linalg.norm(center - p[0]) > 0.10 for p in picked):
            picked.append((center, hex_color))
        if len(picked) == n:
            break
    return [h for _, h in picked]

def luminance(hex_color):
    """How bright a color is, from 0 (black) to 1 (white)."""
    h = hex_color.lstrip("#")
    r, g, b = (int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))

    def fix(c):
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4

    return 0.2126 * fix(r) + 0.7152 * fix(g) + 0.0722 * fix(b)


def contrast(c1, c2):
    """Readability ratio between two colors. 4.5 or more is readable."""
    l1, l2 = luminance(c1), luminance(c2)
    hi, lo = max(l1, l2), min(l1, l2)
    return (hi + 0.05) / (lo + 0.05)

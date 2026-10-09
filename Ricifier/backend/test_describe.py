import json, sys
from fake import FAKE_PALETTE
from ml_model import build_theme

theme = build_theme(sys.argv[1], FAKE_PALETTE)
print(json.dumps(theme, indent=2))
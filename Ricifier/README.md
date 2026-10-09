# Tauri + React

This template should help get you started developing with Tauri and React in Vite.

## Backend workflow

Create an application template from local or HTTPS documentation:

```bash
python -m backend kitty \
  --name "Kitty" \
  --docs https://sw.kovidgoyal.net/kitty/conf/ \
  --out backend/data/applications/kitty
```

Then generate a final key-value configuration from a wallpaper:

```bash
python -m backend.final_generation \
  /path/to/wallpaper.jpg \
  backend/data/applications/kitty \
  --out /tmp/kitty.conf
```

Template creation is handled by `config_generation`. Final generation keeps
the legacy `processor.py` palette extraction and `ml_model.py` Gemma
consultation separate, then validates the resulting values against the
onboarded catalog and policy before writing the config.

## Recommended IDE Setup

- [VS Code](https://code.visualstudio.com/) + [Tauri](https://marketplace.visualstudio.com/items?itemName=tauri-apps.tauri-vscode) + [rust-analyzer](https://marketplace.visualstudio.com/items?itemName=rust-lang.rust-analyzer)

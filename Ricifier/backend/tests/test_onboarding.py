from pathlib import Path
import tempfile
import unittest

from config_generation.onboarding import onboard


class OnboardingTests(unittest.TestCase):
    def test_onboard_local_key_value_docs(self):
        with tempfile.TemporaryDirectory() as directory:
            tmp_path = Path(directory)
            docs = tmp_path / "sample.conf"
            docs.write_text(
                "background #112233\n"
                "foreground #ddeeff\n"
                "font_size 12\n"
                "shell /bin/sh\n",
                encoding="utf-8",
            )
            output = tmp_path / "app"
            paths = onboard("sample", "Sample", [str(docs)], output)

            self.assertEqual(set(paths), {"manifest", "catalog", "template"})
            template = paths["template"].read_text(encoding="utf-8")
            self.assertIn("background {{sample.background}}", template)
            self.assertIn("foreground {{sample.foreground}}", template)
            self.assertNotIn("shell", template)

    def test_onboard_sphinx_html_extracts_defaults(self):
        with tempfile.TemporaryDirectory() as directory:
            tmp_path = Path(directory)
            docs = tmp_path / "docs.html"
            docs.write_text(
                "<html><body><dl><dt>Color scheme</dt><dt>¶</dt>"
                "<dt>foreground</dt><span>¶</span><span>foreground</span>"
                "<span>#ddeeff</span><span>background</span><span>#112233</span>"
                "</body></html>",
                encoding="utf-8",
            )
            paths = onboard("sample", "Sample", [str(docs)], tmp_path / "app")
            names = {
                item["name"]
                for item in __import__("json").loads(
                    paths["catalog"].read_text(encoding="utf-8")
                )["parameters"]
            }
            self.assertEqual(names, {"foreground", "background"})

    def test_constraints_are_extracted_from_documentation(self):
        with tempfile.TemporaryDirectory() as directory:
            tmp_path = Path(directory)
            docs = tmp_path / "docs.txt"
            docs.write_text(
                "tab_bar_style\n¶\n"
                "tab_bar_style\nfade\n"
                "The tab bar style can be one of:\n"
                "fade\nFade style.\n"
                "powerline\nPowerline style.\n"
                "hidden\nHidden style.\n"
                "background_opacity\n¶\n"
                "background_opacity\n1.0\n"
                "The opacity is a number between zero and one.\n",
                encoding="utf-8",
            )
            paths = onboard("sample", "Sample", [str(docs)], tmp_path / "app")
            parameters = {
                item["name"]: item
                for item in __import__("json").loads(
                    paths["catalog"].read_text(encoding="utf-8")
                )["parameters"]
            }
            tab = parameters["tab_bar_style"]
            self.assertEqual(tab["type"], "enum")
            self.assertEqual(
                tab["constraints"]["enum_values"],
                ["fade", "powerline", "hidden"],
            )
            opacity = parameters["background_opacity"]
            self.assertEqual(opacity["constraints"]["min"], 0)
            self.assertEqual(opacity["constraints"]["max"], 1)

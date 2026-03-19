from __future__ import annotations

import json
from datetime import date
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = ROOT / "config" / "pages-seo.json"
TEMPLATE_PATH = ROOT / "templates" / "index.template.html"


def load_config() -> dict[str, object]:
    return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))


def build_schema(config: dict[str, object]) -> str:
    schema = {
        "@context": "https://schema.org",
        "@graph": [
            {
                "@type": "SoftwareApplication",
                "name": str(config["program_name"]),
                "alternateName": str(config["alternate_name"]),
                "applicationCategory": "UtilityApplication",
                "operatingSystem": "Windows",
                "inLanguage": "ko",
                "url": str(config["site_url"]),
                "downloadUrl": str(config["repo_url"]),
                "codeRepository": str(config["repo_url"]),
                "description": str(config["description_en"]),
                "softwareRequirements": "Python 3.11+, Pillow, Windows 10+",
                "offers": {
                    "@type": "Offer",
                    "price": "0",
                    "priceCurrency": "USD",
                },
                "author": {
                    "@type": "Person",
                    "name": str(config["owner"]),
                },
            },
            {
                "@type": "FAQPage",
                "mainEntity": [
                    {
                        "@type": "Question",
                        "name": "Grid Crop Image는 어떤 작업에 잘 맞나요?",
                        "acceptedAnswer": {
                            "@type": "Answer",
                            "text": "스크린샷 분할, 블로그 자산 제작, 반복되는 다중 크롭 작업에 적합합니다.",
                        },
                    },
                    {
                        "@type": "Question",
                        "name": "클립보드 이미지를 바로 붙여넣을 수 있나요?",
                        "acceptedAnswer": {
                            "@type": "Answer",
                            "text": "가능합니다. Ctrl+V로 이미지를 바로 가져와 작업을 시작할 수 있습니다.",
                        },
                    },
                    {
                        "@type": "Question",
                        "name": "JSON 레이아웃을 다시 사용할 수 있나요?",
                        "acceptedAnswer": {
                            "@type": "Answer",
                            "text": "가능합니다. 저장한 크롭 좌표와 설정을 다시 불러와 같은 작업을 반복할 수 있습니다.",
                        },
                    },
                ],
            },
        ],
    }
    return json.dumps(schema, ensure_ascii=False, indent=2)


def render_index_html(config: dict[str, object]) -> str:
    template = TEMPLATE_PATH.read_text(encoding="utf-8")
    replacements = {
        "__SITE_TITLE__": str(config["site_title"]),
        "__DESCRIPTION_KO__": str(config["description_ko"]),
        "__TWITTER_DESCRIPTION__": str(config["twitter_description"]),
        "__KEYWORDS__": ", ".join(str(item) for item in config["keywords"]),
        "__PROGRAM_NAME__": str(config["program_name"]),
        "__ALTERNATE_NAME__": str(config["alternate_name"]),
        "__OWNER__": str(config["owner"]),
        "__SITE_URL__": str(config["site_url"]),
        "__REPO_URL__": str(config["repo_url"]),
        "__README_URL__": str(config["readme_url"]),
        "__SCHEMA_JSON__": build_schema(config),
    }
    rendered = template
    for key, value in replacements.items():
        rendered = rendered.replace(key, value)
    return rendered


def render_robots_txt(config: dict[str, object]) -> str:
    return f"User-agent: *\nAllow: /\n\nSitemap: {config['site_url']}sitemap.xml\n"


def render_sitemap_xml(config: dict[str, object]) -> str:
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
        "  <url>\n"
        f"    <loc>{config['site_url']}</loc>\n"
        f"    <lastmod>{date.today().isoformat()}</lastmod>\n"
        "  </url>\n"
        "</urlset>\n"
    )


def render_manifest(config: dict[str, object]) -> str:
    manifest = {
        "name": str(config["program_name"]),
        "short_name": str(config["program_name"]),
        "description": str(config["description_ko"]),
        "lang": "ko-KR",
        "start_url": str(config["site_url"]),
        "scope": str(config["site_url"]),
        "display": "standalone",
        "theme_color": "#13221a",
        "background_color": "#f6f0e5",
    }
    return json.dumps(manifest, ensure_ascii=False, indent=2) + "\n"


def write_file(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8", newline="\n")


def main() -> int:
    config = load_config()
    write_file(ROOT / "index.html", render_index_html(config))
    write_file(ROOT / "robots.txt", render_robots_txt(config))
    write_file(ROOT / "sitemap.xml", render_sitemap_xml(config))
    write_file(ROOT / "site.webmanifest", render_manifest(config))
    write_file(ROOT / ".nojekyll", "\n")
    print("Generated: index.html, robots.txt, sitemap.xml, site.webmanifest, .nojekyll")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

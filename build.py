"""
build.py  —  Static site builder for Arkesh Das's portfolio website.

Usage:
    uv run python build.py

What this script does:
  1. Reads portfolio_config.yaml.
  2. Loads profile, project, and writing YAML.
  3. Renders templates into dist/.
  4. Copies static assets and writes dist/css/site.css.

After running this script, open dist/index.html in a browser or run
  uv run python serve.py
to preview the site locally.
"""

import argparse
import hashlib
import re
import shutil
import sys
from html import escape
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlparse

import yaml
from jinja2 import Environment, FileSystemLoader, select_autoescape

try:
    import markdown
except ModuleNotFoundError:
    markdown = None


# ── Paths ──────────────────────────────────────────────────────────────────
ROOT = Path(__file__).parent          # repo root
TEMPLATES_DIR = ROOT / "templates"
STATIC_DIR    = ROOT / "static"
BUILD_DIR      = ROOT / "dist"
CONFIG_FILE   = ROOT / "portfolio_config.yaml"


# ── Helpers ────────────────────────────────────────────────────────────────

def load_yaml(path: Path) -> dict:
    """Read a YAML file and return its contents as a Python dictionary."""
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def repo_path(rel_path: str, label: str) -> Path:
    """Resolve a repo-relative path and reject absolute/outside paths."""
    path = (ROOT / rel_path).resolve()
    try:
        path.relative_to(ROOT.resolve())
    except ValueError:
        sys.exit(f"Error: {label} path points outside the repo: {rel_path}")
    return path


def youtube_embed_url(url: str, start_seconds: int = 0, captions: bool = False, captions_lang: str = "en") -> str:
    """Return a YouTube embed URL for common watch/share URL formats."""
    parsed = urlparse(url)
    host = parsed.netloc.lower().removeprefix("www.")

    if host in {"youtube.com", "m.youtube.com"}:
        video_id = parse_qs(parsed.query).get("v", [""])[0]
    elif host == "youtu.be":
        video_id = parsed.path.strip("/").split("/")[0]
    else:
        return url

    video_id = video_id.split("?")[0]
    if not video_id:
        return url

    params = {}
    if start_seconds:
        params["start"] = max(0, int(start_seconds))
    if captions:
        params["cc_load_policy"] = 1
        params["cc_lang_pref"] = captions_lang

    query = f"?{urlencode(params)}" if params else ""
    return f"https://www.youtube-nocookie.com/embed/{video_id}{query}"


def output_path(output_dir: str) -> Path:
    """Resolve a repo-relative output path and reject unsafe targets."""
    path = repo_path(output_dir, "output")
    if path == ROOT:
        sys.exit("Error: refusing to use the repository root as the build output.")
    return path


def clean_build_dir() -> None:
    """Remove generated output before rebuilding."""
    if BUILD_DIR.exists():
        shutil.rmtree(BUILD_DIR)
    BUILD_DIR.mkdir(parents=True, exist_ok=True)


def should_copy_static_file(path: Path) -> bool:
    """Skip local metadata files that should not be published."""
    return not path.is_absolute() and ".." not in path.parts and not any(part.startswith(".") for part in path.parts)


def copy_static_asset(asset_path: str) -> None:
    """Copy one referenced static asset into dist/."""
    if not asset_path:
        return

    relative = Path(asset_path)
    if not should_copy_static_file(relative):
        print(f"  [warn] Skipping unsafe static asset path: {asset_path}")
        return

    src = STATIC_DIR / relative
    dest = BUILD_DIR / relative
    if not src.exists():
        return

    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dest)
    print(f"  copied  static/{relative}")


def markdown_image_paths(text: str) -> list[str]:
    """Return local static image paths referenced by Markdown image syntax."""
    paths = []
    for match in re.finditer(r"!\[[^\]]*\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)", text or ""):
        path = match.group(1).strip()
        if path.startswith(("http://", "https://", "data:", "#")):
            continue
        paths.append(path.removeprefix("static/"))
    return paths


def copy_post_assets(post: dict) -> None:
    """Copy assets named by a writing post."""
    copy_static_asset(post.get("image_path"))

    for image in post.get("images", []):
        if isinstance(image, dict):
            copy_static_asset(image.get("path"))
        elif isinstance(image, str):
            copy_static_asset(image)

    for media in post.get("media", []):
        if isinstance(media, dict):
            copy_static_asset(media.get("path"))

    for image_path in markdown_image_paths(post.get("raw_content", "")):
        copy_static_asset(image_path)


def copy_scholarship_assets(scholarship: dict) -> None:
    """Copy assets named by scholarship page content."""
    featured = scholarship.get("featured_project", {})
    copy_static_asset(featured.get("paper_path"))

    for project in scholarship.get("additional_projects", []):
        copy_static_asset(project.get("poster_url"))


def copy_referenced_assets(student: dict, projects: list[dict], writing_posts: list[dict], scholarship: dict) -> None:
    """Copy only assets referenced by YAML content."""
    copy_static_asset(student.get("headshot"))

    for project in projects:
        copy_static_asset(project.get("image_path"))

    for post in writing_posts:
        copy_post_assets(post)

    copy_scholarship_assets(scholarship)


def toggle_themes(theme: str, theme_toggle: dict) -> list[str]:
    """Return configured toggle themes, preserving order and uniqueness."""
    if not theme_toggle.get("enabled"):
        return []

    themes = [
        theme_toggle.get("light_theme") or theme,
        theme_toggle.get("dark_theme"),
    ]
    return list(dict.fromkeys(t for t in themes if t))


def stylesheet_fingerprint(theme: str, theme_toggle: dict | None = None) -> str:
    """Create a cache-busting version from the actual source CSS."""
    digest = hashlib.sha256()
    theme_toggle = theme_toggle or {}
    theme_names = list(dict.fromkeys([theme, *toggle_themes(theme, theme_toggle)]))
    paths = [
        STATIC_DIR / "css" / "base.css",
        *[STATIC_DIR / "css" / "themes" / f"{theme_name}.css" for theme_name in theme_names],
    ]
    for path in paths:
        digest.update(path.read_bytes())
    return digest.hexdigest()[:12]


def scoped_theme_css(css: str, theme: str) -> str:
    """Scope theme selectors to an html data attribute for toggling."""
    scope = f'html[data-site-theme="{theme}"]'

    def scoped_selector(selector: str) -> str:
        parts = []
        for part in selector.split(","):
            item = part.strip()
            if item:
                parts.append(f"{scope} {item}")
        return ",\n".join(parts)

    def replace(match: re.Match) -> str:
        return f"{scoped_selector(match.group(1))} {{{match.group(2)}}}\n"

    return re.sub(r"(?s)([^{}@][^{}]+?)\s*\{([^{}]*)\}", replace, css)


def write_combined_styles(theme: str, theme_toggle: dict | None = None) -> None:
    """Combine base.css, default theme, and optional scoped toggle themes."""
    theme_toggle = theme_toggle or {}
    base_css = STATIC_DIR / "css" / "base.css"
    theme_css = STATIC_DIR / "css" / "themes" / f"{theme}.css"
    output_css = BUILD_DIR / "css" / "site.css"

    if not base_css.exists():
        sys.exit(f"Error: base stylesheet not found: {base_css}")
    if not theme_css.exists():
        sys.exit(f"Error: theme stylesheet not found: {theme_css}")

    toggle_theme_names = [
        theme_name for theme_name in toggle_themes(theme, theme_toggle)
        if theme_name != theme
    ]
    for theme_name in toggle_theme_names:
        path = STATIC_DIR / "css" / "themes" / f"{theme_name}.css"
        if not path.exists():
            sys.exit(f"Error: toggle theme '{theme_name}' not found at static/css/themes/{theme_name}.css")

    stylesheet_parts = [
        "/* Generated by build.py. Do not edit dist/css/site.css directly. */\n\n",
        f"/* base.css */\n{base_css.read_text(encoding='utf-8')}\n\n",
        f"/* themes/{theme}.css */\n{theme_css.read_text(encoding='utf-8')}\n",
    ]
    for theme_name in toggle_theme_names:
        path = STATIC_DIR / "css" / "themes" / f"{theme_name}.css"
        stylesheet_parts.append(
            f"\n/* themes/{theme_name}.css scoped */\n"
            f"{scoped_theme_css(path.read_text(encoding='utf-8'), theme_name)}\n"
        )

    output_css.parent.mkdir(parents=True, exist_ok=True)
    output_css.write_text("".join(stylesheet_parts), encoding="utf-8")

    scoped_names = "".join(f" + scoped {name}" for name in toggle_theme_names)
    print(f"  wrote   css/site.css  (base + {theme}{scoped_names})")


def warn_if_missing_static_asset(asset_path: str, context: str) -> None:
    if not asset_path:
        return

    if not should_copy_static_file(Path(asset_path)):
        print(f"  [warn] Unsafe asset path for {context}: {asset_path}")
        return

    p = STATIC_DIR / asset_path
    if not p.exists():
        print(f"  [warn] Missing asset for {context}: static/{asset_path}")


def require_fields(item: dict, fields: list[str], context: str) -> None:
    missing = [field for field in fields if item.get(field) in (None, "")]
    if missing:
        sys.exit(f"Error: {context} is missing required field(s): {', '.join(missing)}")


def validate_student(student: dict) -> None:
    require_fields(student, ["name", "role", "headline"], "student profile")
    warn_if_missing_static_asset(student.get("headshot"), "student headshot")

    endpoint = student.get("formspree_endpoint", "")
    if endpoint and "YOUR_FORM_ID" in endpoint:
        print("  [warn] Formspree endpoint still uses YOUR_FORM_ID placeholder.")

    video_url = student.get("featured_video_url")
    embed_url = student.get("featured_video_embed_url")
    if video_url and embed_url == video_url:
        print(f"  [warn] Featured video URL was not converted to an embed URL: {video_url}")


def validate_projects(projects: list[dict]) -> None:
    for project in projects:
        title = project.get("title", "Untitled project")
        require_fields(project, ["title", "short_summary"], f"project '{title}'")
        warn_if_missing_static_asset(project.get("image_path"), title)


def validate_writing_post(post: dict) -> None:
    title = post.get("title", "Untitled post")
    require_fields(post, ["title", "date", "short_summary"], f"writing post '{title}'")

    if post.get("has_original_post") and not post.get("original_post_url"):
        sys.exit(f"Error: writing post '{title}' has_original_post is true but original_post_url is empty.")

    if post.get("original_post_url") and not post.get("has_original_post"):
        print(f"  [warn] Writing post '{title}' has original_post_url but has_original_post is false.")

    warn_if_missing_static_asset(post.get("image_path"), f"writing post '{title}'")
    for image in post.get("images", []):
        image_path = image.get("path") if isinstance(image, dict) else image
        warn_if_missing_static_asset(image_path, f"writing post '{title}'")
    for media in post.get("media", []):
        if isinstance(media, dict):
            warn_if_missing_static_asset(media.get("path"), f"writing post '{title}'")
    for image_path in markdown_image_paths(post.get("raw_content", "")):
        warn_if_missing_static_asset(image_path, f"writing post '{title}'")


def markdown_field(item: dict, field: str) -> None:
    """Convert a Markdown field in-place when present."""
    if item.get(field):
        item[field] = render_markdown(item[field])


def inline_markdown(text: str) -> str:
    """Render a small subset of inline Markdown for fallback builds."""
    text = escape(text)
    text = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", text)
    text = re.sub(r"\*(.+?)\*", r"<em>\1</em>", text)
    return text


def fallback_markdown(text: str) -> str:
    """Minimal Markdown renderer for paragraphs and simple lists."""
    blocks = re.split(r"\n\s*\n", text.strip())
    html_blocks = []

    for block in blocks:
        lines = [line.strip() for line in block.splitlines() if line.strip()]
        if not lines:
            continue

        if all(line.startswith(("- ", "* ")) for line in lines):
            items = "".join(f"<li>{inline_markdown(line[2:].strip())}</li>" for line in lines)
            html_blocks.append(f"<ul>{items}</ul>")
            continue

        paragraph = " ".join(lines)
        html_blocks.append(f"<p>{inline_markdown(paragraph)}</p>")

    return "\n".join(html_blocks)


def render_markdown(text: str) -> str:
    """Render Markdown with the dependency when available, otherwise fallback."""
    if markdown:
        return markdown.markdown(text)
    return fallback_markdown(text)


def slugify(value: str) -> str:
    """Create a URL-safe slug from a title or filename stem."""
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug or "post"


def unique_slug(preferred: str, used: set[str]) -> str:
    """Return a unique slug, preserving the preferred value when possible."""
    slug = preferred
    counter = 2
    while slug in used:
        slug = f"{preferred}-{counter}"
        counter += 1
    used.add(slug)
    return slug


def load_optional_yaml(rel_path: str, label: str) -> dict:
    """Load an optional YAML file, warning instead of failing when absent."""
    if not rel_path:
        return {}

    path = repo_path(rel_path, label)
    if not path.exists():
        print(f"  [warn] {label} file not found, skipping: {rel_path}")
        return {}

    return load_yaml(path)


def render_page(env: Environment, template_name: str, output_rel: str, **context) -> None:
    """Render one template into dist/."""
    output_path = BUILD_DIR / output_rel
    output_path.parent.mkdir(parents=True, exist_ok=True)
    rendered = env.get_template(template_name).render(**context)
    rendered = "\n".join(line.rstrip() for line in rendered.splitlines()) + "\n"
    output_path.write_text(rendered, encoding="utf-8")
    print(f"       rendered: {output_path.relative_to(ROOT)}")


def render_markdown_tree(value, fields: set[str] | None = None) -> None:
    """Render markdown in nested conference content structures."""
    markdown_fields = fields or {
        "summary",
        "body",
        "bio",
        "note",
        "details",
        "abstract",
        "intro",
        "lead",
        "content",
    }

    if isinstance(value, dict):
        for key, child in list(value.items()):
            if isinstance(child, str) and child and key in markdown_fields:
                value[key] = render_markdown(child)
            else:
                render_markdown_tree(child, markdown_fields)
    elif isinstance(value, list):
        for item in value:
            render_markdown_tree(item, markdown_fields)


def collect_local_assets(value) -> None:
    """Copy local static assets referenced anywhere in conference content."""
    asset_keys = {"image_path", "logo_path", "photo_path", "map_image", "paper_path", "pdf_path", "hero_image_path"}

    if isinstance(value, dict):
        for key, child in value.items():
            if isinstance(child, str) and child and key in asset_keys:
                copy_static_asset(child)
            else:
                collect_local_assets(child)
    elif isinstance(value, list):
        for item in value:
            collect_local_assets(item)


def validate_conference(conference: dict) -> None:
    """Validate the conference site content."""
    require_fields(conference, ["site_name", "abbrev", "hero_title", "hero_tagline", "hero_summary", "dates", "location"], "conference content")
    require_fields(conference.get("primary_cta", {}), ["label", "url"], "conference primary CTA")
    require_fields(conference.get("secondary_cta", {}), ["label", "url"], "conference secondary CTA")


# ── Main build ─────────────────────────────────────────────────────────────

def build(output_dir: str = "dist") -> None:
    global BUILD_DIR
    BUILD_DIR = output_path(output_dir)

    print("=" * 55)
    print(f"  Building conference site → {BUILD_DIR.relative_to(ROOT)}/")
    print("=" * 55)

    # ── 1. Load config ──────────────────────────────────────────────────
    if not CONFIG_FILE.exists():
        sys.exit(f"Error: {CONFIG_FILE} not found. Are you running from the repo root?")

    config = load_yaml(CONFIG_FILE)
    print(f"\n[1/4] Loaded config:  {CONFIG_FILE.name}")

    theme       = config.get("theme", "light")
    theme_toggle = config.get("theme_toggle", {})
    site_title  = config.get("site_title", "Conference website")
    google_site_verification = config.get("google_site_verification", "")
    conference_rel = config.get("conference_file", "content/conference.yaml")

    theme_path = STATIC_DIR / "css" / "themes" / f"{theme}.css"
    if not theme_path.exists():
        sys.exit(f"Error: theme '{theme}' not found at static/css/themes/{theme}.css")
    asset_version = stylesheet_fingerprint(theme, theme_toggle)

    # ── 2. Load conference content ─────────────────────────────────────
    conference_path = repo_path(conference_rel, "conference")
    if not conference_path.exists():
        sys.exit(f"Error: conference file '{conference_rel}' not found.")

    conference = load_yaml(conference_path)
    render_markdown_tree(conference)
    validate_conference(conference)
    print(f"[2/4] Loaded conference content: {conference_path.name}")

    # ── 6. Render HTML ──────────────────────────────────────────────────
    clean_build_dir()

    env = Environment(
        loader=FileSystemLoader(str(TEMPLATES_DIR)),
        autoescape=select_autoescape(["html"]),
    )
    env.filters["slugify"] = slugify

    base_context = {
        "site_title": site_title,
        "theme": theme,
        "asset_version": asset_version,
        "theme_toggle": theme_toggle,
        "google_site_verification": google_site_verification,
        "conference": conference,
    }

    print("\n      Rendering pages …")
    render_page(
        env,
        "index.html",
        "index.html",
        **base_context,
        current_page="home",
        site_root="",
        show_hero=True,
    )
    page_routes = [
        ("call_for_papers", "call-for-papers/index.html"),
        ("committee", "committee/index.html"),
        ("speakers", "speakers/index.html"),
        ("submission", "submission/index.html"),
        ("registration", "registration/index.html"),
        ("contact", "contact/index.html"),
    ]
    for page_name, output_rel in page_routes:
        page = conference.get("pages", {}).get(page_name)
        if not page:
            sys.exit(f"Error: conference page '{page_name}' is missing from {conference_path.name}.")
        render_page(
            env,
            "page.html",
            output_rel,
            **base_context,
            page=page,
            current_page=page_name,
            site_root="../",
            show_hero=False,
        )
    print("[3/4] Rendered site pages.")

    # ── 6. Copy static assets ───────────────────────────────────────────
    print("\n      Writing static assets …")
    collect_local_assets(conference)
    write_combined_styles(theme, theme_toggle)
    (BUILD_DIR / ".nojekyll").write_text("", encoding="utf-8")
    print("  wrote   .nojekyll")

    print(f"\n✓  Build complete.  Open {BUILD_DIR.relative_to(ROOT)}/index.html or run: uv run python serve.py")
    print("=" * 55)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Build the portfolio static site.")
    parser.add_argument(
        "--output",
        default="dist",
        help="Repo-relative output directory for generated site files. Defaults to dist.",
    )
    args = parser.parse_args()
    build(args.output)

#!/usr/bin/env python3
"""
WICID Firmware Build Tool

Interactive CLI tool and build engine for creating firmware release packages.
Generates manifests, compiles bytecode, creates ZIP packages, and generates releases.json.
Also builds/minifies captive portal web assets (src/www → build/www).

Full reset strategy: every release contains complete firmware (no partial updates).
Note: releases.json is generated but not committed (gitignored, deployed separately).
"""

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path

# Optional minifiers / HTML parser (graceful fallback if not installed)
try:
    from rjsmin import jsmin as _jsmin
except Exception:
    _jsmin = None
try:
    from rcssmin import cssmin as _cssmin
except Exception:
    _cssmin = None
# Require htmlmin2 distribution, but import its module name "htmlmin"
try:
    from importlib.metadata import distribution

    import htmlmin as _htmlmin  # module provided by htmlmin2

    # hard-check that the installed provider is *htmlmin2*, not legacy htmlmin
    distribution("htmlmin2")  # raises if htmlmin2 dist isn't installed
except Exception:
    _htmlmin = None
try:
    from bs4 import BeautifulSoup as _BS
except Exception:
    _BS = None


# Color codes for terminal output
class Colors:
    HEADER = "\033[95m"
    OKBLUE = "\033[94m"
    OKCYAN = "\033[96m"
    OKGREEN = "\033[92m"
    WARNING = "\033[93m"
    FAIL = "\033[91m"
    ENDC = "\033[0m"
    BOLD = "\033[1m"


def print_header(text):
    """Print a formatted header."""
    print(f"\n{Colors.HEADER}{Colors.BOLD}{text}{Colors.ENDC}")
    print("=" * len(text))


def print_success(text):
    """Print success message."""
    print(f"{Colors.OKGREEN}✓ {text}{Colors.ENDC}")


def print_error(text):
    """Print error message."""
    print(f"{Colors.FAIL}✗ {text}{Colors.ENDC}")


def print_warning(text):
    """Print warning message."""
    print(f"{Colors.WARNING}⚠ {text}{Colors.ENDC}")


def calculate_sha256(file_path, chunk_size=65536):
    """
    Calculate SHA-256 checksum of a file.

    Args:
        file_path: Path to file to checksum
        chunk_size: Bytes to read per iteration (default: 64KB for speed)

    Returns:
        str: Hexadecimal SHA-256 checksum
    """
    sha256 = hashlib.sha256()
    with open(file_path, "rb") as f:
        while True:
            chunk = f.read(chunk_size)
            if not chunk:
                break
            sha256.update(chunk)
    return sha256.hexdigest()


def get_git_status():
    """Check if git working directory is clean."""
    try:
        result = subprocess.run(["git", "status", "--porcelain"], capture_output=True, text=True, check=True)
        return len(result.stdout.strip()) == 0
    except subprocess.CalledProcessError:
        return False


def has_staged_files():
    """Check if there are any files staged for commit."""
    try:
        result = subprocess.run(["git", "diff", "--cached", "--name-only"], capture_output=True, text=True, check=True)
        return len(result.stdout.strip()) > 0
    except subprocess.CalledProcessError:
        return False


def load_previous_manifest():
    """Load previous src/manifest.json for default values."""
    manifest_file = Path("src/manifest.json")
    if manifest_file.exists():
        with open(manifest_file) as f:
            return json.load(f)
    return None


def load_releases_json():
    """Load existing releases.json or create empty structure."""
    releases_file = Path("releases.json")
    if releases_file.exists():
        with open(releases_file) as f:
            return json.load(f)
    else:
        return {"schema_version": "1.0.0", "last_updated": "", "releases": []}


def save_releases_json(releases_data):
    """Save releases.json with pretty formatting."""
    with open("releases.json", "w") as f:
        json.dump(releases_data, f, indent=2)
        f.write("\n")  # Add trailing newline


# === Captive portal (www) build helpers (minimal integration) ===
def _minify_css(css: str) -> str:
    """Minify CSS using rcssmin if available, else return original."""
    if _cssmin:
        try:
            return _cssmin(css)
        except Exception:
            return css
    return css


def _minify_js(js: str) -> str:
    """Minify JS using rjsmin if available, else return original."""
    if _jsmin:
        try:
            return _jsmin(js)
        except Exception:
            return js
    return js


def _minify_html(html: str) -> str:
    """Minify HTML using htmlmin2/htmlmin if available, else collapse simple whitespace."""
    if _htmlmin:
        try:
            return _htmlmin.minify(
                html,
                remove_comments=True,
                remove_empty_space=True,
                reduce_boolean_attributes=True,
                remove_optional_attribute_quotes=False,
            )
        except Exception:
            return html
    # very light fallback: trim leading/trailing spaces on lines
    return "\n".join(line.strip() for line in html.splitlines() if line.strip())


def _inline_single_file_html(html: str, css_min: str, js_min: str) -> str:
    """
    Inline CSS and JS into provided HTML. Uses BeautifulSoup when available,
    otherwise falls back to conservative regex replacements.
    """
    if _BS:
        soup = _BS(html, "html.parser")
        # Replace <link rel="stylesheet" ...> with <style>...</style>
        link = soup.find("link", rel="stylesheet")
        if link:
            style_tag = soup.new_tag("style")
            style_tag.string = css_min
            link.replace_with(style_tag)
        # Replace first <script src=...> with inline script at end of body
        script = soup.find("script", src=True)
        if script:
            inline = soup.new_tag("script")
            inline.string = js_min
            script.decompose()
            if soup.body:
                soup.body.append(inline)
            else:
                soup.append(inline)
        return str(soup)
    # Conservative regex fallback (use function repl to prevent backslash escapes)
    link_pat = re.compile(r'<link[^>]+rel=["\']stylesheet["\'][^>]*>', re.IGNORECASE)
    html_out = link_pat.sub(lambda _m: "<style>" + css_min + "</style>", html, count=1)
    script_pat = re.compile(r'<script[^>]+src=["\'][^"\']+["\'][^>]*>\s*</script>', re.IGNORECASE)
    html_out = script_pat.sub(lambda _m: "<script>" + js_min + "</script>", html_out, count=1)
    return html_out


def build_www_assets(src_www: Path, out_root: Path, mode: str = "single") -> None:
    """
    Build the captive portal www assets into build/www.
      mode: "single" (default), "split", or "both"
    Outputs (always under build/www):
      - single: index.html (inline CSS/JS)
      - split/both: design-tokens.min.css, main.min.js, and index.html pointing to them
    """
    index_path = src_www / "index.html"
    css_path = src_www / "design-tokens.css"
    js_path = src_www / "main.js"

    if not index_path.exists():
        print_warning("www/index.html not found; copying www directory as-is.")
        shutil.copytree(src_www, out_root / "www", dirs_exist_ok=True)
        return

    index_html = index_path.read_text(encoding="utf-8")
    css_text = css_path.read_text(encoding="utf-8") if css_path.exists() else ""
    js_text = js_path.read_text(encoding="utf-8") if js_path.exists() else ""

    css_min = _minify_css(css_text)
    js_min = _minify_js(js_text)

    out_www = out_root / "www"
    out_www.mkdir(parents=True, exist_ok=True)

    # Split build (optional)
    if mode in ("split", "both"):
        (out_www / "design-tokens.min.css").write_text(css_min or "", encoding="utf-8")
        (out_www / "main.min.js").write_text(js_min or "", encoding="utf-8")
        html_split = index_html
        if _BS:
            soup = _BS(html_split, "html.parser")
            link = soup.find("link", rel="stylesheet")
            if link:
                link["href"] = "./design-tokens.min.css"
            script = soup.find("script", src=True)
            if script:
                script["src"] = "./main.min.js"
            html_split = str(soup)
        else:
            html_split = re.sub(
                r'<link([^>]+)href=["\'][^"\']+["\']',
                r'<link\1href="./design-tokens.min.css"',
                html_split,
                count=1,
                flags=re.IGNORECASE,
            )
            html_split = re.sub(
                r'<script([^>]+)src=["\'][^"\']+["\']',
                r'<script\1src="./main.min.js"',
                html_split,
                count=1,
                flags=re.IGNORECASE,
            )

        (out_www / "index.html").write_text(_minify_html(html_split), encoding="utf-8")
        print_success(f"Built split www → {out_www}")

    # Single-file build (default) — always writes index.html under build/www/
    if mode in ("single", "both"):
        html_single = _inline_single_file_html(index_html, css_min, js_min)
        (out_www / "index.html").write_text(_minify_html(html_single), encoding="utf-8")
        print_success(f"Built single-file www → {out_www}")

    # Copy any additional static assets (e.g., favicon.svg, inline svgs, logos)
    for p in src_www.iterdir():
        if p.is_file() and p.name not in ("index.html", "design-tokens.css", "main.js"):
            target = out_www / p.name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(p, target)

    # Warn if minifiers are missing
    if (_cssmin is None) or (_jsmin is None) or (_htmlmin is None):
        print_warning("Minifier packages not fully installed. Install with:")
        print_warning("  pip install rcssmin rjsmin htmlmin2 beautifulsoup4")


def parse_version(version_str):
    """
    Validate and parse semantic version string.

    Pattern: INT.INT.INT[optional "-" + (a|b|rc|rtm|ga)[optional digits]]
    Examples: "1.2.3", "1.2.3-b", "1.2.3-b2", "1.2.3-rc1"

    Returns:
        tuple: (version_tuple, has_prerelease) or None if invalid
    """
    if not version_str:
        return None

    # Validate format: ^\d+\.\d+\.\d+(?:-(?:a|b|rc|rtm|ga)(?:\d+)?)?$
    pattern = r"^\d+\.\d+\.\d+(?:-(?:a|b|rc|rtm|ga)(?:\d+)?)?$"
    if not re.match(pattern, version_str):
        return None

    # Split on '-' to separate version from pre-release tag
    parts = version_str.split("-")
    version_parts = parts[0].split(".")

    try:
        version_tuple = tuple(int(x) for x in version_parts)
        has_prerelease = len(parts) > 1
        return (version_tuple, has_prerelease)
    except ValueError:
        return None


def extract_base_version(version_str):
    """
    Extract base version (without suffix) from version string.

    Examples:
        "1.2.3" -> "1.2.3"
        "1.2.3-b2" -> "1.2.3"
    """
    if not version_str:
        return None
    parts = version_str.split("-")
    return parts[0] if parts else None


def extract_suffix(version_str):
    """
    Extract pre-release suffix from version string.

    Examples:
        "1.2.3" -> None
        "1.2.3-b2" -> "b2"
        "1.2.3-rc" -> "rc"
    """
    if not version_str:
        return None
    parts = version_str.split("-", 1)
    return parts[1] if len(parts) > 1 else None


def suggest_versions(current_version):
    """Suggest patch, minor, and major version increments."""
    # Extract base version (strip suffix) for suggestions
    base_version = extract_base_version(current_version)
    if not base_version:
        return []

    parsed = parse_version(base_version)
    if not parsed:
        return []

    version_tuple, _ = parsed

    if len(version_tuple) == 3:
        major, minor, patch = version_tuple
        return [
            f"{major}.{minor}.{patch + 1}",  # Patch
            f"{major}.{minor + 1}.0",  # Minor
            f"{major + 1}.0.0",  # Major
        ]
    return []


def read_current_version():
    """Read current VERSION from src/settings.toml."""
    try:
        with open("src/settings.toml") as f:
            for line in f:
                if line.startswith("VERSION"):
                    # Parse: VERSION = "0.1.0"
                    return line.split("=")[1].strip().strip('"')
    except Exception as e:
        print_warning(f"Could not read version from settings.toml: {e}")
    return "0.0.0"


def update_version_in_settings(new_version):
    """Update VERSION in src/settings.toml."""
    settings_path = Path("src/settings.toml")

    try:
        with open(settings_path) as f:
            lines = f.readlines()

        with open(settings_path, "w") as f:
            for line in lines:
                if line.startswith("VERSION"):
                    f.write(f'VERSION = "{new_version}"\n')
                else:
                    f.write(line)

        print_success(f"Updated VERSION in settings.toml: {new_version}")
    except Exception as e:
        print_error(f"Could not update settings.toml: {e}")
        raise


def interactive_build():
    """Interactive CLI for creating a firmware release."""
    print_header("🔧 WICID Firmware Build Tool")

    # Check git status
    if get_git_status():
        print_success("Git status: Clean")
    else:
        print_warning("Git status: Uncommitted changes")

    # Load previous manifest for defaults
    prev_manifest = load_previous_manifest()

    # Load existing releases
    releases_data = load_releases_json()

    # Determine current version for display (prefer manifest, fallback to settings.toml)
    if prev_manifest and "version" in prev_manifest:
        current_version = prev_manifest["version"]
    else:
        current_version = read_current_version()
    print(f"\nCurrent version: {current_version}")

    # 1. Target Machine Types
    print("\n1. Target Machine Types (comma-separated, full strings):")
    if prev_manifest:
        default_machines = ", ".join(
            prev_manifest.get("target_machine_types", ["Adafruit Feather ESP32S3 4MB Flash 2MB PSRAM with ESP32S3"])
        )
        print(f"   Last release: {default_machines}")
    else:
        default_machines = "Adafruit Feather ESP32S3 4MB Flash 2MB PSRAM with ESP32S3"

    machines_input = input(f"   [{default_machines}]: ").strip()
    target_machines = [m.strip() for m in (machines_input or default_machines).split(",")]

    # 2. Target Operating Systems
    print("\n2. Target Operating Systems (comma-separated, format: os_major_minor):")
    if prev_manifest:
        default_oses = ", ".join(prev_manifest.get("target_operating_systems", ["circuitpython_10_1"]))
        print(f"   Last release: {default_oses}")
    else:
        default_oses = "circuitpython_10_1"

    oses_input = input(f"   [{default_oses}]: ").strip()
    target_oses = [o.strip() for o in (oses_input or default_oses).split(",")]

    # 3. Release Type
    print("\n3. Release Type:")
    print("   a) Production")
    print("   b) Development")
    if prev_manifest:
        default_release_type = prev_manifest.get("release_type", "production")
        default_prompt = "Production" if default_release_type == "production" else "Development"
    else:
        default_release_type = "production"
        default_prompt = "Production"
    release_type_input = input(f"   [{default_prompt}]: ").strip().lower()
    if not release_type_input:
        release_type = default_release_type
    else:
        release_type = "development" if release_type_input in ["b", "dev", "development"] else "production"

    # 4. Version Number
    print("\n4. Version Number:")
    # Use manifest base version as default, or fallback to suggestions from settings.toml
    if prev_manifest and "version" in prev_manifest:
        default_base_version = extract_base_version(prev_manifest["version"])
        if default_base_version:
            suggestions = suggest_versions(default_base_version)
            if suggestions:
                print(f"   Suggestions: {suggestions[0]} (patch), {suggestions[1]} (minor), {suggestions[2]} (major)")
            default_version = default_base_version
        else:
            # Fallback if manifest version is invalid
            current_settings_version = read_current_version()
            suggestions = suggest_versions(current_settings_version)
            default_version = suggestions[0] if suggestions else "0.2.0"
    else:
        current_settings_version = read_current_version()
        suggestions = suggest_versions(current_settings_version)
        default_version = suggestions[0] if suggestions else "0.2.0"

    version = input(f"   Enter version [{default_version}]: ").strip()
    if not version:
        version = default_version

    # Validate version format
    if not parse_version(version):
        print_error("Invalid version format. Use format: X.Y.Z (e.g., 1.2.3)")
        return False

    # Extract any existing suffix from the entered version
    entered_suffix = extract_suffix(version)
    base_version_entered = extract_base_version(version)

    # 4a. Pre-release suffix (only for Development releases)
    if release_type == "development":
        print("\n4a. Pre-release Suffix:")
        print("   Options: a, b, rc, rtm, or ga")
        print("   You can add a number after the suffix (e.g., b2, rc1)")

        # Determine default suffix: use entered suffix if present, otherwise use manifest suffix
        default_suffix = None
        if entered_suffix:
            default_suffix = entered_suffix
        elif prev_manifest and "version" in prev_manifest:
            existing_suffix = extract_suffix(prev_manifest["version"])
            if existing_suffix:
                default_suffix = existing_suffix

        suffix_prompt = f"   [{default_suffix if default_suffix else 'none'}]: "
        suffix_input = input(suffix_prompt).strip()

        if suffix_input:
            # Validate suffix format: must be one of the allowed suffixes optionally followed by digits
            suffix_pattern = r"^(a|b|rc|rtm|ga)(\d+)?$"
            if not re.match(suffix_pattern, suffix_input.lower()):
                print_error(
                    "Invalid suffix format. Use: a, b, rc, rtm, or ga (optionally followed by digits, e.g., b2)"
                )
                return False
            # Use base version and append new suffix
            version = f"{base_version_entered}-{suffix_input.lower()}"
            # Re-validate full version
            if not parse_version(version):
                print_error("Invalid version format with suffix.")
                return False
        elif default_suffix:
            # Use default suffix if user didn't provide one (either from entered version or manifest)
            version = f"{base_version_entered}-{default_suffix}"
        # If no suffix input and no default, version remains as base version (no suffix)

    # 5. Release Notes
    print("\n5. Release Notes:")
    if prev_manifest:
        default_notes = prev_manifest.get("release_notes", "")
        if default_notes:
            print(f"   Last release: {default_notes}")
    else:
        default_notes = ""

    notes_input = input(f"   [{default_notes if default_notes else 'None'}]: ").strip()
    release_notes = notes_input if notes_input else default_notes

    # Build the release
    print_header("Building Release")

    try:
        # Update VERSION in settings.toml
        update_version_in_settings(version)

        # Create manifest
        manifest = create_manifest(
            version=version,
            target_machines=target_machines,
            target_oses=target_oses,
            release_type=release_type,
            release_notes=release_notes,
        )

        # Save manifest to src/
        print_success("Saving src/manifest.json...")
        with open("src/manifest.json", "w") as f:
            json.dump(manifest, f, indent=2)
            f.write("\n")

        # Build package (returns path and checksum)
        package_path, checksum = build_package(manifest, version)

        # Update releases.json with checksum
        print_success("Updating releases.json...")
        releases_data = load_releases_json()
        update_releases_json(releases_data, manifest, target_machines, target_oses, release_type, version, checksum)
        save_releases_json(releases_data)

        # Show preview
        show_preview(manifest, package_path, current_version)

        # Phase 2: Commit and tag workflow
        committed = False
        tagged = False
        pushed = False
        commit_sha = None
        tag_name = None

        artifacts = ["src/settings.toml", "src/manifest.json"]

        print_header("Phase 2: Commit and Tag")
        print("\nBuild artifacts ready:")
        for artifact in artifacts:
            print(f"  • {artifact}")
        print("  • releases.json (generated, not committed)")

        print("\nContinue with committing build artifacts? [y/N]: ", end="")
        if input().strip().lower() == "y":
            # Check for staged files
            if has_staged_files():
                print_warning("\nThere are files already staged in git.")
                print("Please clear the staging area before continuing:")
                print("  • Commit staged changes: git commit")
                print("  • Unstage changes: git reset")
                print_error("\nAborting phase 2. Build artifacts are ready but not committed.")
            else:
                # Stage the build artifacts
                stage_files()

                # Get commit message
                commit_msg = get_commit_message(version, release_notes)
                if commit_msg:
                    # Commit the changes
                    commit_sha = commit_files(commit_msg)
                    if commit_sha:
                        committed = True
                        print_success(f"Committed changes: {commit_sha[:7]}")

                        # Ask about creating tag
                        print("\nCreate release tag? [y/N]: ", end="")
                        if input().strip().lower() == "y":
                            tag_msg = get_tag_message(version, release_notes)
                            if tag_msg:
                                tag_name = create_git_tag(version, tag_msg)
                                if tag_name:
                                    tagged = True

                                    # Ask about pushing
                                    print("\nPush commit and tag to remote? [y/N]: ", end="")
                                    if input().strip().lower() == "y":
                                        pushed = push_changes(tag_name)

        # Show summary
        show_build_summary(version, package_path, committed, tagged, pushed, commit_sha, tag_name, artifacts)

        return True

    except Exception as e:
        print_error(f"Build failed: {e}")
        import traceback

        traceback.print_exc()
        return False


def create_manifest(version, target_machines, target_oses, release_type, release_notes):
    """Create manifest.json structure for full reset strategy."""
    manifest = {
        "schema_version": "1.0.0",
        "version": version,
        "target_machine_types": target_machines,
        "target_operating_systems": target_oses,
        "release_type": release_type,
        "release_notes": release_notes,
        "release_date": datetime.now(timezone.utc).isoformat(),
    }
    return manifest


def update_releases_json(releases_data, manifest, target_machines, target_oses, release_type, version, sha256_checksum):
    """Update releases.json with new multi-platform structure."""
    # Find existing release entry matching these machine types and OSes
    release_entry = None
    for entry in releases_data["releases"]:
        if (
            entry.get("target_machine_types") == target_machines
            and entry.get("target_operating_systems") == target_oses
        ):
            release_entry = entry
            break

    # Create new entry if it doesn't exist
    if not release_entry:
        release_entry = {"target_machine_types": target_machines, "target_operating_systems": target_oses}
        releases_data["releases"].append(release_entry)

    # Update the release type section
    zip_url = f"https://www.wicid.ai/releases/v{version}"

    release_entry[release_type] = {
        "version": manifest["version"],
        "release_notes": manifest["release_notes"],
        "zip_url": zip_url,
        "sha256": sha256_checksum,
        "release_date": manifest["release_date"],
    }

    # Sort releases by most recent date
    def get_latest_date(entry):
        dates = []
        for rt in ["production", "development"]:
            if rt in entry and "release_date" in entry[rt]:
                dates.append(entry[rt]["release_date"])
        return max(dates) if dates else ""

    releases_data["releases"].sort(key=get_latest_date, reverse=True)
    releases_data["last_updated"] = datetime.now(timezone.utc).isoformat()


def build_package(manifest, version):
    """Build the release package with bytecode compilation and web asset build."""
    print_success("Compiling Python to bytecode...")

    # Create releases directory
    releases_dir = Path("releases")
    releases_dir.mkdir(exist_ok=True)

    # Package is always named wicid_install.zip
    package_name = "wicid_install.zip"
    package_path = releases_dir / package_name

    # Create build directory
    build_dir = Path("build")
    if build_dir.exists():
        shutil.rmtree(build_dir)
    build_dir.mkdir()

    # Compile Python files to bytecode
    src_path = Path("src")

    for py_file in src_path.glob("**/*.py"):
        # Exclude boot.py and code.py from compilation - CircuitPython requires them as source files
        if py_file.name in ("boot.py", "code.py"):
            shutil.copy2(py_file, build_dir / py_file.name)
            continue
        rel_path = py_file.relative_to(src_path)
        mpy_rel_path = str(rel_path)[:-3] + ".mpy"
        mpy_file = build_dir / mpy_rel_path

        # Create parent directories
        mpy_file.parent.mkdir(parents=True, exist_ok=True)

        try:
            # Compile with mpy-cross
            result = subprocess.run(
                ["mpy-cross", str(py_file), "-o", str(mpy_file)], check=True, capture_output=True, text=True
            )
            if result.stdout:
                print(result.stdout.strip())
            print(f"  Compiled: {rel_path}")
        except subprocess.CalledProcessError as e:
            print_error(f"  Failed to compile {rel_path} with mpy-cross")
            if e.stderr:
                print(e.stderr.strip())
            if e.stdout:
                print(e.stdout.strip())
            raise

    # Copy non-Python files (special-case www)
    for item in src_path.iterdir():
        if item.is_file() and not item.name.endswith(".py"):
            shutil.copy2(item, build_dir / item.name)
            print(f"  Copied: {item.name}")
        elif item.is_dir() and item.name not in ["__pycache__"]:
            if item.name == "www":
                # Build minified/combined web UI into build/www
                www_mode = os.environ.get("WICID_WWW_MODE", "single").lower()
                if www_mode not in ("single", "split", "both"):
                    www_mode = "single"
                print_success(f"Building www assets (mode={www_mode})...")
                build_www_assets(item, build_dir, mode=www_mode)
            else:
                shutil.copytree(item, build_dir / item.name, dirs_exist_ok=True)
                print(f"  Copied: {item.name}/")

    # Copy manifest.json to build directory
    shutil.copy2("src/manifest.json", build_dir / "manifest.json")

    # Create ZIP package
    print_success(f"Creating package: {package_name}...")

    with zipfile.ZipFile(package_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for file in build_dir.rglob("*"):
            if file.is_file():
                arcname = file.relative_to(build_dir)
                zf.write(file, arcname)
                print(f"  Added: {arcname}")

    validate_build_artifacts(build_dir)

    # Clean up build directory
    shutil.rmtree(build_dir)

    print_success(f"Package created: {package_path}")

    # Calculate SHA-256 checksum
    print_success("Calculating SHA-256 checksum...")
    checksum = calculate_sha256(package_path)
    print(f"  SHA-256: {checksum}")

    return package_path, checksum


def validate_build_artifacts(build_dir: Path):
    """Validate critical files exist and have expected formats after build."""
    errors = []

    boot_py = build_dir / "boot.py"
    if not boot_py.exists():
        errors.append("boot.py missing")
    elif boot_py.suffix != ".py":
        errors.append("boot.py must remain source (.py)")

    code_py = build_dir / "code.py"
    if not code_py.exists():
        errors.append("code.py missing")
    elif code_py.suffix != ".py":
        errors.append("code.py must remain source (.py)")

    critical_mpy = [
        "boot_support.mpy",
        "code_support.mpy",
        "utils.mpy",
    ]
    for filename in critical_mpy:
        if not (build_dir / filename).exists():
            errors.append(f"{filename} missing")

    for py_file in build_dir.glob("*.py"):
        if py_file.name not in ("boot.py", "code.py"):
            errors.append(f"Unexpected source file at root: {py_file.name}")

    if errors:
        detail = "\n".join(f"  - {msg}" for msg in errors)
        raise Exception(f"Build validation failed:\n{detail}")


def show_preview(manifest, package_path, old_version):
    """Show preview of the release."""
    print_header("Release Preview")
    print(f"  Version:           {old_version} → {manifest['version']}")
    print(f"  Release Type:      {manifest['release_type']}")
    print(f"  Machine Types:     {', '.join(manifest['target_machine_types'])}")
    print(f"  Operating Systems: {', '.join(manifest['target_operating_systems'])}")
    print(f"  Release Notes:     {manifest['release_notes']}")
    print(f"  Package:           {package_path}")
    print(f"  Package Size:      {package_path.stat().st_size / 1024:.1f} KB")


def get_commit_message(version, release_notes):
    """Get commit message from user with option to customize."""
    default_msg = f"Release v{version}"
    if release_notes:
        default_msg += f"\n\n{release_notes}"

    print("\nProposed commit message:")
    print("-" * 60)
    print(default_msg)
    print("-" * 60)
    print("\nAccept this message? [Y/n/edit]: ", end="")
    response = input().strip().lower()

    if response == "n":
        print("Commit cancelled.")
        return None
    elif response == "edit":
        print("\nEnter new commit message (press Ctrl+D when done):")
        lines = []
        try:
            while True:
                line = input()
                lines.append(line)
        except EOFError:
            pass
        custom_msg = "\n".join(lines).strip()
        return custom_msg if custom_msg else None
    else:  # 'y' or empty (default yes)
        return default_msg


def commit_files(commit_message):
    """Commit staged files and return commit SHA."""
    try:
        subprocess.run(["git", "commit", "-m", commit_message], capture_output=True, text=True, check=True)
        # Get the commit SHA
        sha_result = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True, check=True)
        return sha_result.stdout.strip()
    except subprocess.CalledProcessError as e:
        print_error(f"Failed to commit files: {e}")
        return None


def get_tag_message(version, release_notes):
    """Get tag message from user with option to customize."""
    default_msg = f"Release {version}"
    if release_notes:
        default_msg += f"\n\n{release_notes}"

    print("\nProposed tag message:")
    print("-" * 60)
    print(default_msg)
    print("-" * 60)
    print("\nAccept this message? [Y/n/edit]: ", end="")
    response = input().strip().lower()

    if response == "n":
        print("Tag creation cancelled.")
        return None
    elif response == "edit":
        print("\nEnter new tag message (press Ctrl+D when done):")
        lines = []
        try:
            while True:
                line = input()
                lines.append(line)
        except EOFError:
            pass
        custom_msg = "\n".join(lines).strip()
        return custom_msg if custom_msg else None
    else:  # 'y' or empty (default yes)
        return default_msg


def create_git_tag(version, tag_message):
    """Create git tag in v{version} format with custom message."""
    tag_name = f"v{version}"

    try:
        subprocess.run(["git", "tag", "-a", tag_name, "-m", tag_message], capture_output=True, text=True, check=True)
        print_success(f"Created git tag: {tag_name}")
        return tag_name
    except subprocess.CalledProcessError as e:
        print_error(f"Failed to create git tag: {e}")
        return None


def stage_files():
    """Stage manifest files for commit."""
    files_to_stage = ["src/settings.toml", "src/manifest.json"]

    try:
        subprocess.run(["git", "add"] + files_to_stage, check=True)
    except subprocess.CalledProcessError as e:
        print_error(f"Failed to stage files: {e}")
        raise


def push_changes(tag_name):
    """Push commits and tags to remote."""
    try:
        # Push the branch
        print("Pushing commits to remote...")
        subprocess.run(["git", "push"], capture_output=True, text=True, check=True)
        print_success("Commits pushed successfully")

        # Push the tag
        print("Pushing tag to remote...")
        subprocess.run(["git", "push", "origin", tag_name], capture_output=True, text=True, check=True)
        print_success(f"Tag {tag_name} pushed successfully")
        return True
    except subprocess.CalledProcessError as e:
        print_error(f"Failed to push changes: {e}")
        if e.stderr:
            print(f"Error: {e.stderr}")
        return False


def show_build_summary(version, package_path, committed, tagged, pushed, commit_sha, tag_name, artifacts):
    """Show comprehensive summary of build process."""
    print_header("Build Summary")

    print(f"\n  Version:        {version}")
    print(f"  Package:        {package_path}")
    print(f"  Package Size:   {package_path.stat().st_size / 1024:.1f} KB")

    print("\n  Build Artifacts:")
    for artifact in artifacts:
        print(f"    • {artifact}")

    if committed:
        print(f"\n  ✓ Committed:    {commit_sha}")
    else:
        print("\n  ✗ Not committed")
        print("\n  Manual commit steps:")
        print("    1. Stage files: git add src/settings.toml src/manifest.json")
        print(f'    2. Commit: git commit -m "Release v{version}"')

    if tagged:
        print(f"  ✓ Tagged:       {tag_name}")
    else:
        print("  ✗ Not tagged")
        if committed:
            print("\n  Manual tag steps:")
            print(f"    1. Create tag: git tag -a {f'v{version}'} -m \"Release {version}\"")

    if pushed:
        print("  ✓ Pushed:       remote updated")
    else:
        print("  ✗ Not pushed")
        if tagged:
            print("\n  Manual push steps:")
            print("    1. Push commits: git push")
            print(f"    2. Push tag: git push origin {tag_name}")
        elif committed:
            print("\n  Manual push steps:")
            print("    1. Create and push tag first (see above)")
            print("    2. Then push: git push && git push --tags")

    if pushed:
        print("\n  Next steps:")
        print("    • Monitor GitHub Actions for release build")
        print("    • Verify release appears on GitHub")

    print()


def show_help():
    """Display help information."""
    help_text = f"""
{Colors.HEADER}{Colors.BOLD}WICID Firmware Build Tool{Colors.ENDC}

Interactive CLI tool and build engine for creating firmware release packages.
Generates manifests, compiles bytecode, creates ZIP packages, generates releases.json,
and builds/minifies captive portal web assets.

{Colors.BOLD}USAGE:{Colors.ENDC}
    builder.py              Run interactive build wizard
    builder.py --build      Non-interactive build from existing manifest
    builder.py --help       Display this help message

{Colors.BOLD}WORKFLOW:{Colors.ENDC}
    1. Updates VERSION in src/settings.toml
    2. Creates/updates src/manifest.json
    3. Compiles Python files to bytecode (.mpy)
    4. Builds and minifies captive portal web assets (src/www → build/www)
       • CSS and JS minified (rcssmin / rjsmin)
       • index.html combined with inline CSS/JS (htmlmin2/htmlmin)
       • Default mode: single (inline)
       • Override with WICID_WWW_MODE=split|both
    5. Bundles firmware into releases/wicid_install.zip
    6. Generates releases.json (gitignored)
    7. Optionally commits, tags (v{{version}}), and pushes to git

{Colors.BOLD}FILES:{Colors.ENDC}
    src/settings.toml       VERSION definition (committed)
    src/manifest.json       Release metadata (auto-generated, committed)
    src/www/                Captive portal sources (HTML/CSS/JS)
    build/www/              Built web assets (single-file index.html by default)
    releases.json           Release index (auto-generated, gitignored)
    releases/               Built firmware packages (gitignored)

Default captive portal build mode: single (inline CSS/JS).
Override with env var:
    WICID_WWW_MODE=split   # external minified CSS/JS alongside index.html
    WICID_WWW_MODE=both    # produce both inline index.html AND external minified assets
"""
    print(help_text)


def main():
    """Main entry point."""
    if len(sys.argv) > 1:
        arg = sys.argv[1]
        if arg in ("--help", "-h"):
            show_help()
            sys.exit(0)
        elif arg == "--build":
            # Non-interactive build mode (for CI)
            print("Building from existing manifest...")
            with open("src/manifest.json") as f:
                manifest = json.load(f)
            version = manifest["version"]
            package_path, checksum = build_package(manifest, version)
            print_success(f"Build complete: {package_path}")
            print_success(f"SHA-256: {checksum}")

            # Update releases.json with checksum
            print("Updating releases.json with checksum...")
            releases_data = load_releases_json()
            update_releases_json(
                releases_data,
                manifest,
                manifest["target_machine_types"],
                manifest["target_operating_systems"],
                manifest["release_type"],
                version,
                checksum,
            )
            save_releases_json(releases_data)
            print_success("releases.json updated")
            sys.exit(0)
        else:
            print_error(f"Unknown option: {arg}")
            print("Run 'builder.py --help' for usage information.")
            sys.exit(1)
    else:
        # Interactive mode
        success = interactive_build()
        sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()

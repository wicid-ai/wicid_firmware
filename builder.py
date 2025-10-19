#!/usr/bin/env python3
"""
WICID Firmware Build Tool

Interactive CLI tool and build engine for creating firmware release packages.
Generates manifests, compiles bytecode, creates ZIP packages, and updates releases.json.

Full reset strategy: every release contains complete firmware (no partial updates).
"""

import sys
import os
import json
import subprocess
import zipfile
import shutil
from datetime import datetime, timezone
from pathlib import Path

# Color codes for terminal output
class Colors:
    HEADER = '\033[95m'
    OKBLUE = '\033[94m'
    OKCYAN = '\033[96m'
    OKGREEN = '\033[92m'
    WARNING = '\033[93m'
    FAIL = '\033[91m'
    ENDC = '\033[0m'
    BOLD = '\033[1m'


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


def get_git_status():
    """Check if git working directory is clean."""
    try:
        result = subprocess.run(
            ['git', 'status', '--porcelain'],
            capture_output=True,
            text=True,
            check=True
        )
        return len(result.stdout.strip()) == 0
    except subprocess.CalledProcessError:
        return False


def load_previous_manifest():
    """Load previous src/manifest.json for default values."""
    manifest_file = Path("src/manifest.json")
    if manifest_file.exists():
        with open(manifest_file, 'r') as f:
            return json.load(f)
    return None


def load_releases_json():
    """Load existing releases.json or create empty structure."""
    releases_file = Path("releases.json")
    if releases_file.exists():
        with open(releases_file, 'r') as f:
            return json.load(f)
    else:
        return {
            "schema_version": "1.0.0",
            "last_updated": "",
            "releases": []
        }


def save_releases_json(releases_data):
    """Save releases.json with pretty formatting."""
    with open("releases.json", 'w') as f:
        json.dump(releases_data, f, indent=2)
        f.write('\n')  # Add trailing newline


def parse_version(version_str):
    """Parse semantic version string into tuple."""
    # Split on '-' to separate version from pre-release tag
    parts = version_str.split('-')
    version_parts = parts[0].split('.')
    
    try:
        version_tuple = tuple(int(x) for x in version_parts)
        has_prerelease = len(parts) > 1
        return (version_tuple, has_prerelease)
    except ValueError:
        return None


def suggest_versions(current_version):
    """Suggest patch, minor, and major version increments."""
    parsed = parse_version(current_version)
    if not parsed:
        return []
    
    version_tuple, has_prerelease = parsed
    
    # Remove prerelease suffix for suggestions
    if len(version_tuple) == 3:
        major, minor, patch = version_tuple
        return [
            f"{major}.{minor}.{patch + 1}",  # Patch
            f"{major}.{minor + 1}.0",        # Minor
            f"{major + 1}.0.0"                # Major
        ]
    return []


def read_current_version():
    """Read current VERSION from src/settings.toml."""
    try:
        with open("src/settings.toml", 'r') as f:
            for line in f:
                if line.startswith('VERSION'):
                    # Parse: VERSION = "0.1.0"
                    return line.split('=')[1].strip().strip('"')
    except Exception as e:
        print_warning(f"Could not read version from settings.toml: {e}")
    return "0.0.0"


def update_version_in_settings(new_version):
    """Update VERSION in src/settings.toml."""
    settings_path = Path("src/settings.toml")
    
    try:
        with open(settings_path, 'r') as f:
            lines = f.readlines()
        
        with open(settings_path, 'w') as f:
            for line in lines:
                if line.startswith('VERSION'):
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
    
    # Read current version
    current_version = read_current_version()
    print(f"\nCurrent version: {current_version}")
    
    # 1. Target Machine Types
    print("\n1. Target Machine Types (comma-separated, full strings):")
    if prev_manifest:
        default_machines = ', '.join(prev_manifest.get('target_machine_types', ['Adafruit Feather ESP32S3 4MB Flash 2MB PSRAM with ESP32S3']))
        print(f"   Last release: {default_machines}")
    else:
        default_machines = "Adafruit Feather ESP32S3 4MB Flash 2MB PSRAM with ESP32S3"
    
    machines_input = input(f"   [{default_machines}]: ").strip()
    target_machines = [m.strip() for m in (machines_input or default_machines).split(',')]
    
    # 2. Target Operating Systems
    print("\n2. Target Operating Systems (comma-separated, format: os_major_minor):")
    if prev_manifest:
        default_oses = ', '.join(prev_manifest.get('target_operating_systems', ['circuitpython_10_1']))
        print(f"   Last release: {default_oses}")
    else:
        default_oses = "circuitpython_10_1"
    
    oses_input = input(f"   [{default_oses}]: ").strip()
    target_oses = [o.strip() for o in (oses_input or default_oses).split(',')]
    
    # 3. Release Type
    print("\n3. Release Type:")
    print("   a) Production")
    print("   b) Development")
    release_type_input = input("   [Production]: ").strip().lower()
    release_type = "development" if release_type_input in ['b', 'dev', 'development'] else "production"
    
    # 4. Version Number
    print("\n4. Version Number:")
    suggestions = suggest_versions(current_version)
    if suggestions:
        print(f"   Suggestions: {suggestions[0]} (patch), {suggestions[1]} (minor), {suggestions[2]} (major)")
    version = input(f"   Enter version [{suggestions[0] if suggestions else '0.2.0'}]: ").strip()
    if not version:
        version = suggestions[0] if suggestions else "0.2.0"
    
    # Validate version format
    if not parse_version(version):
        print_error("Invalid version format. Use semantic versioning (e.g., 1.2.3 or 1.2.3-beta.1)")
        return False
    
    # 5. Release Notes
    print("\n5. Release Notes:")
    release_notes = input("   > ").strip()
    
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
            release_notes=release_notes
        )
        
        # Save manifest to src/
        print_success("Saving src/manifest.json...")
        with open("src/manifest.json", 'w') as f:
            json.dump(manifest, f, indent=2)
            f.write('\n')
        
        # Update releases.json
        print_success(f"Updating releases.json...")
        update_releases_json(releases_data, manifest, target_machines, target_oses, release_type, version)
        save_releases_json(releases_data)
        
        # Build package
        package_path = build_package(manifest, version)
        
        # Show preview
        show_preview(manifest, package_path, current_version)
        
        # Create git tag and stage files
        print("\nReady to create git tag and stage files? [y/N]: ", end='')
        if input().strip().lower() == 'y':
            create_git_tag(version)
            stage_files()
            print_success("\nFiles staged for commit:")
            print("    src/settings.toml")
            print("    src/manifest.json")
            print("    releases.json")
            print_header("Next steps")
            print("  1. Review changes: git diff --staged")
            print(f"  2. Commit: git commit -m \"Release {version}\"")
            print("  3. Push: git push && git push --tags")
            print("  4. Monitor GitHub Actions: releases will be built automatically")
        
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


def update_releases_json(releases_data, manifest, target_machines, target_oses, release_type, version):
    """Update releases.json with new multi-platform structure."""
    # Find existing release entry matching these machine types and OSes
    release_entry = None
    for entry in releases_data["releases"]:
        if (entry.get("target_machine_types") == target_machines and
            entry.get("target_operating_systems") == target_oses):
            release_entry = entry
            break
    
    # Create new entry if it doesn't exist
    if not release_entry:
        release_entry = {
            "target_machine_types": target_machines,
            "target_operating_systems": target_oses
        }
        releases_data["releases"].append(release_entry)
    
    # Update the release type section
    zip_url = f"https://github.com/bmcnaboe/wicid_firmware/releases/download/v{version}/wicid_install.zip"
    
    release_entry[release_type] = {
        "version": manifest["version"],
        "release_notes": manifest["release_notes"],
        "zip_url": zip_url,
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
    """Build the release package with bytecode compilation."""
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
        mpy_rel_path = str(rel_path)[:-3] + '.mpy'
        mpy_file = build_dir / mpy_rel_path

        # Create parent directories
        mpy_file.parent.mkdir(parents=True, exist_ok=True)

        try:
            # Compile with mpy-cross
            subprocess.run(
                ['mpy-cross', str(py_file), '-o', str(mpy_file)],
                check=True,
                capture_output=True
            )
            print(f"  Compiled: {rel_path}")
        except subprocess.CalledProcessError as e:
            print_warning(f"  Could not compile {rel_path}: {e}")
            # Fall back to copying source file
            shutil.copy2(py_file, build_dir / rel_path)
    
    # Copy non-Python files
    for item in src_path.iterdir():
        if item.is_file() and not item.name.endswith('.py'):
            shutil.copy2(item, build_dir / item.name)
            print(f"  Copied: {item.name}")
        elif item.is_dir() and item.name not in ['__pycache__']:
            shutil.copytree(item, build_dir / item.name, dirs_exist_ok=True)
            print(f"  Copied: {item.name}/")
    
    # Copy manifest.json to build directory
    shutil.copy2("src/manifest.json", build_dir / "manifest.json")
    
    # Create ZIP package
    print_success(f"Creating package: {package_name}...")
    
    with zipfile.ZipFile(package_path, 'w', zipfile.ZIP_DEFLATED) as zf:
        for file in build_dir.rglob('*'):
            if file.is_file():
                arcname = file.relative_to(build_dir)
                zf.write(file, arcname)
                print(f"  Added: {arcname}")
    
    # Clean up build directory
    shutil.rmtree(build_dir)
    
    print_success(f"Package created: {package_path}")
    return package_path


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


def create_git_tag(version):
    """Create git tag in v{version} format."""
    tag_name = f"v{version}"
    
    try:
        subprocess.run(
            ['git', 'tag', '-a', tag_name, '-m', f'Release {version}'],
            check=True
        )
        print_success(f"Created git tag: {tag_name}")
    except subprocess.CalledProcessError as e:
        print_error(f"Failed to create git tag: {e}")
        raise


def stage_files():
    """Stage manifest and releases files for commit."""
    files_to_stage = [
        "src/settings.toml",
        "src/manifest.json",
        "releases.json"
    ]
    
    try:
        subprocess.run(['git', 'add'] + files_to_stage, check=True)
    except subprocess.CalledProcessError as e:
        print_error(f"Failed to stage files: {e}")
        raise


def main():
    """Main entry point."""
    if len(sys.argv) > 1 and sys.argv[1] == '--build':
        # Non-interactive build mode (for GitHub Actions)
        print("Building from existing manifest...")
        # Load manifest and build
        with open("src/manifest.json", 'r') as f:
            manifest = json.load(f)
        version = manifest['version']
        package_path = build_package(manifest, version)
        print_success(f"Build complete: {package_path}")
    else:
        # Interactive mode
        success = interactive_build()
        sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()

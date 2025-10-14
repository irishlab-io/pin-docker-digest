import argparse
import sys
import subprocess
import json
import yaml
from pathlib import Path
from typing import Any


def get_image_digest(image_name: str) -> str | None:
    """
    Get the digest for a Docker image using docker manifest inspect.

    Args:
        image_name: The Docker image name (e.g., 'python:3.9-slim-buster')

    Returns:
        The SHA256 digest of the image, or None if not found
    """
    try:
        # Use docker manifest inspect to get the digest
        result = subprocess.run(
            ["docker", "manifest", "inspect", image_name],
            capture_output=True,
            text=True,
            check=True,
        )

        manifest = json.loads(result.stdout)

        # For multi-platform manifests
        if (
            "mediaType" in manifest
            and manifest["mediaType"]
            == "application/vnd.docker.distribution.manifest.list.v2+json"
        ):
            # Get the first manifest (or you could filter by platform)
            if "manifests" in manifest and len(manifest["manifests"]) > 0:
                digest = manifest["manifests"][0]["digest"]
                return digest

        # For single platform manifests
        if "config" in manifest and "digest" in manifest["config"]:
            return manifest["config"]["digest"]

        # Try to get digest from Docker-Content-Digest header
        result = subprocess.run(
            ["docker", "manifest", "inspect", "--verbose", image_name],
            capture_output=True,
            text=True,
            check=True,
        )

        # Look for the digest in the verbose output
        lines = result.stderr.split("\n")
        for line in lines:
            if "Docker-Content-Digest:" in line:
                digest = line.split("Docker-Content-Digest:")[1].strip()
                return digest

    except subprocess.CalledProcessError as e:
        print(f"Error getting digest for {image_name}: {e}", file=sys.stderr)
        return None
    except json.JSONDecodeError as e:
        print(f"Error parsing manifest for {image_name}: {e}", file=sys.stderr)
        return None
    except Exception as e:
        print(f"Unexpected error getting digest for {image_name}: {e}", file=sys.stderr)
        return None

    return None


def extract_images_from_compose(
    compose_data: dict[str, Any],
) -> list[tuple[str, list[str]]]:
    """
    Extract all Docker images from a docker-compose data structure.

    Args:
        compose_data: Parsed docker-compose YAML data

    Returns:
        List of tuples containing (service_name, [path, to, image, key])
    """
    images = []

    def find_images_recursive(data: Any, path: list[str] = []):
        if isinstance(data, dict):
            for key, value in data.items():
                current_path = path + [key]
                if key == "image" and isinstance(value, str):
                    # Check if image is not already pinned with digest
                    if "@sha256:" not in value:
                        images.append((value, current_path))
                else:
                    find_images_recursive(value, current_path)
        elif isinstance(data, list):
            for i, item in enumerate(data):
                find_images_recursive(item, path + [str(i)])

    find_images_recursive(compose_data)
    return images


def update_image_in_compose_data(
    compose_data: dict[str, Any], path: list[str], new_image: str
) -> dict[str, Any]:
    """
    Update an image reference in the compose data structure.

    Args:
        compose_data: The compose data to modify
        path: Path to the image key (e.g., ['services', 'web', 'image'])
        new_image: The new image reference with digest

    Returns:
        Updated compose data
    """
    current = compose_data

    # Navigate to the parent of the target
    for key in path[:-1]:
        current = current[key]

    # Update the final key
    current[path[-1]] = new_image

    return compose_data


def pin_compose_images(compose_path: Path, dry_run: bool = False) -> bool:
    """
    Pin all images in a docker-compose.yml file to their digest versions.

    Args:
        compose_path: Path to the docker-compose.yml file
        dry_run: If True, only show what would be changed without modifying files

    Returns:
        True if successful, False otherwise
    """
    print(f"Processing {compose_path}")

    try:
        with open(compose_path) as f:
            compose_data = yaml.safe_load(f)
    except yaml.YAMLError as e:
        print(f"Error parsing YAML in {compose_path}: {e}", file=sys.stderr)
        return False
    except Exception as e:
        print(f"Error reading {compose_path}: {e}", file=sys.stderr)
        return False

    if not compose_data:
        print(f"Empty or invalid compose file: {compose_path}")
        return False

    # Extract all images
    images = extract_images_from_compose(compose_data)

    if not images:
        print(f"No unpinned images found in {compose_path}")
        return True

    changes_made = False
    modified_data = compose_data.copy()

    for image_name, path in images:
        print(f"  Found image: {image_name} (at {'.'.join(path)})")

        # Get the digest for this image
        digest = get_image_digest(image_name)

        if digest:
            # Remove tag and add digest
            if ":" in image_name:
                image_base = image_name.split(":")[0]
            else:
                image_base = image_name

            pinned_image = f"{image_base}@{digest}"

            print(f"    -> Pinning to: {pinned_image}")

            if dry_run:
                print(f"    -> Would replace: {image_name}")
                print(f"    ->           with: {pinned_image}")
            else:
                # Update in the data structure
                modified_data = update_image_in_compose_data(
                    modified_data, path, pinned_image
                )
                changes_made = True
        else:
            print(f"    -> Warning: Could not get digest for {image_name}")

    # Write back the modified content
    if changes_made and not dry_run:
        try:
            with open(compose_path, "w") as f:
                yaml.dump(modified_data, f, default_flow_style=False, sort_keys=False)
            print(f"  ✓ Updated {compose_path}")
        except Exception as e:
            print(f"Error writing {compose_path}: {e}", file=sys.stderr)
            return False
    elif dry_run:
        print("  (dry run - no changes made)")

    return True


def find_compose_files(directory: Path) -> list[Path]:
    """
    Find all docker-compose files in a directory recursively.

    Args:
        directory: Directory to search

    Returns:
        List of docker-compose file paths
    """
    compose_files = []

    # Common docker-compose file patterns
    patterns = [
        "docker-compose.yml",
        "docker-compose.yaml",
        "compose.yml",
        "compose.yaml",
        "docker-compose.*.yml",
        "docker-compose.*.yaml",
    ]

    for pattern in patterns:
        compose_files.extend(directory.rglob(pattern))

    return list(set(compose_files))  # Remove duplicates


def main():
    """Main CLI entry point."""
    parser = argparse.ArgumentParser(
        description="Pin Docker images in docker-compose.yml files to their digest versions",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  pin-compose                           # Pin images in ./docker-compose.yml
  pin-compose --path ./docker           # Pin images in all compose files under ./docker
  pin-compose --dry-run                 # Show what would be changed without modifying files
  pin-compose compose.yml               # Pin images in specific compose file
        """,
    )

    parser.add_argument(
        "files",
        nargs="*",
        help="Specific docker-compose file(s) to process. If not provided, searches for compose files in current directory",
    )

    parser.add_argument(
        "--path",
        type=Path,
        default=Path.cwd(),
        help="Directory to search for docker-compose files (default: current directory)",
    )

    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be changed without modifying files",
    )

    parser.add_argument(
        "--verbose", "-v", action="store_true", help="Enable verbose output"
    )

    args = parser.parse_args()

    # Determine which files to process
    if args.files:
        compose_paths = [Path(f) for f in args.files]
        # Validate that all specified files exist
        for path in compose_paths:
            if not path.exists():
                print(f"Error: {path} does not exist", file=sys.stderr)
                return 1
    else:
        # Find compose files in the specified path
        compose_paths = find_compose_files(args.path)

        if not compose_paths:
            print(f"No docker-compose files found in {args.path}")
            return 0

    success = True

    for compose_path in compose_paths:
        if not pin_compose_images(compose_path, dry_run=args.dry_run):
            success = False

    if success:
        print("\n✓ All docker-compose files processed successfully")
        return 0
    else:
        print("\n✗ Some errors occurred during processing")
        return 1


if __name__ == "__main__":
    sys.exit(main())

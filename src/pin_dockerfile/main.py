import argparse
import re
import sys
import subprocess
import json
from pathlib import Path
from typing import List, Dict, Tuple, Optional


def get_image_digest(image_name: str) -> Optional[str]:
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
            check=True
        )
        
        manifest = json.loads(result.stdout)
        
        # For multi-platform manifests
        if "mediaType" in manifest and manifest["mediaType"] == "application/vnd.docker.distribution.manifest.list.v2+json":
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
            check=True
        )
        
        # Look for the digest in the verbose output
        lines = result.stderr.split('\n')
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


def parse_dockerfile_images(dockerfile_path: Path) -> List[Tuple[str, str, int]]:
    """
    Parse a Dockerfile and extract all FROM statements.
    
    Args:
        dockerfile_path: Path to the Dockerfile
        
    Returns:
        List of tuples containing (original_line, image_name, line_number)
    """
    images = []
    
    try:
        with open(dockerfile_path, 'r') as f:
            lines = f.readlines()
            
        for i, line in enumerate(lines, 1):
            # Match FROM statements (case insensitive)
            match = re.match(r'^FROM\s+([^\s]+)', line.strip(), re.IGNORECASE)
            if match:
                image_name = match.group(1)
                # Skip if already pinned with digest
                if '@sha256:' not in image_name:
                    images.append((line.rstrip(), image_name, i))
                    
    except FileNotFoundError:
        print(f"Error: Dockerfile not found at {dockerfile_path}", file=sys.stderr)
    except Exception as e:
        print(f"Error reading Dockerfile {dockerfile_path}: {e}", file=sys.stderr)
        
    return images


def pin_dockerfile_images(dockerfile_path: Path, dry_run: bool = False) -> bool:
    """
    Pin all images in a Dockerfile to their digest versions.
    
    Args:
        dockerfile_path: Path to the Dockerfile
        dry_run: If True, only show what would be changed without modifying files
        
    Returns:
        True if successful, False otherwise
    """
    print(f"Processing {dockerfile_path}")
    
    images = parse_dockerfile_images(dockerfile_path)
    
    if not images:
        print(f"No unpinned images found in {dockerfile_path}")
        return True
    
    # Read the entire file
    try:
        with open(dockerfile_path, 'r') as f:
            content = f.read()
    except Exception as e:
        print(f"Error reading {dockerfile_path}: {e}", file=sys.stderr)
        return False
    
    modified_content = content
    changes_made = False
    
    for original_line, image_name, line_number in images:
        print(f"  Found image: {image_name} (line {line_number})")
        
        # Get the digest for this image
        digest = get_image_digest(image_name)
        
        if digest:
            # Remove tag and add digest
            if ':' in image_name:
                image_base = image_name.split(':')[0]
            else:
                image_base = image_name
                
            pinned_image = f"{image_base}@{digest}"
            new_line = original_line.replace(image_name, pinned_image)
            
            print(f"    -> Pinning to: {pinned_image}")
            
            if dry_run:
                print(f"    -> Would replace: {original_line.strip()}")
                print(f"    ->           with: {new_line.strip()}")
            else:
                # Replace in content
                modified_content = modified_content.replace(original_line, new_line)
                changes_made = True
        else:
            print(f"    -> Warning: Could not get digest for {image_name}")
    
    # Write back the modified content
    if changes_made and not dry_run:
        try:
            with open(dockerfile_path, 'w') as f:
                f.write(modified_content)
            print(f"  ✓ Updated {dockerfile_path}")
        except Exception as e:
            print(f"Error writing {dockerfile_path}: {e}", file=sys.stderr)
            return False
    elif dry_run:
        print(f"  (dry run - no changes made)")
    
    return True


def find_dockerfiles(directory: Path) -> List[Path]:
    """
    Find all Dockerfiles in a directory recursively.
    
    Args:
        directory: Directory to search
        
    Returns:
        List of Dockerfile paths
    """
    dockerfiles = []
    
    # Common Dockerfile patterns
    patterns = ['Dockerfile', 'Dockerfile.*', '*.dockerfile']
    
    for pattern in patterns:
        dockerfiles.extend(directory.rglob(pattern))
    
    return list(set(dockerfiles))  # Remove duplicates


def main():
    """Main CLI entry point."""
    parser = argparse.ArgumentParser(
        description="Pin Dockerfile images to their digest versions",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  pin-dockerfile                    # Pin images in ./Dockerfile
  pin-dockerfile --path ./docker    # Pin images in all Dockerfiles under ./docker
  pin-dockerfile --dry-run          # Show what would be changed without modifying files
  pin-dockerfile Dockerfile         # Pin images in specific Dockerfile
        """
    )
    
    parser.add_argument(
        "files",
        nargs="*",
        help="Specific Dockerfile(s) to process. If not provided, searches for Dockerfiles in current directory"
    )
    
    parser.add_argument(
        "--path",
        type=Path,
        default=Path.cwd(),
        help="Directory to search for Dockerfiles (default: current directory)"
    )
    
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be changed without modifying files"
    )
    
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Enable verbose output"
    )
    
    args = parser.parse_args()
    
    # Determine which files to process
    if args.files:
        dockerfile_paths = [Path(f) for f in args.files]
        # Validate that all specified files exist
        for path in dockerfile_paths:
            if not path.exists():
                print(f"Error: {path} does not exist", file=sys.stderr)
                return 1
    else:
        # Find Dockerfiles in the specified path
        dockerfile_paths = find_dockerfiles(args.path)
        
        if not dockerfile_paths:
            print(f"No Dockerfiles found in {args.path}")
            return 0
    
    success = True
    
    for dockerfile_path in dockerfile_paths:
        if not pin_dockerfile_images(dockerfile_path, dry_run=args.dry_run):
            success = False
    
    if success:
        print("\n✓ All Dockerfiles processed successfully")
        return 0
    else:
        print("\n✗ Some errors occurred during processing")
        return 1


if __name__ == "__main__":
    sys.exit(main())

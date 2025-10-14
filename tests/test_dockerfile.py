import pytest
import tempfile
import subprocess
from pathlib import Path
from unittest.mock import patch, MagicMock

from src.pin_dockerfile.main import (
    parse_dockerfile_images,
    get_image_digest,
    pin_dockerfile_images,
    find_dockerfiles
)


class TestParseDockerfileImages:
    def test_parse_simple_dockerfile(self):
        """Test parsing a simple Dockerfile with FROM statements."""
        content = """
FROM python:3.9-slim-buster
WORKDIR /app
FROM node:16-alpine
COPY . .
        """.strip()

        with tempfile.NamedTemporaryFile(mode='w', suffix='Dockerfile', delete=False) as f:
            f.write(content)
            f.flush()

            images = parse_dockerfile_images(Path(f.name))

        assert len(images) == 2
        assert images[0][1] == "python:3.9-slim-buster"
        assert images[1][1] == "node:16-alpine"

        # Clean up
        Path(f.name).unlink()

    def test_parse_dockerfile_with_digest(self):
        """Test that images already pinned with digest are skipped."""
        content = """
FROM python:3.9-slim-buster
FROM node:16-alpine@sha256:abcd1234
FROM redis:6.2
        """.strip()

        with tempfile.NamedTemporaryFile(mode='w', suffix='Dockerfile', delete=False) as f:
            f.write(content)
            f.flush()

            images = parse_dockerfile_images(Path(f.name))

        # Should only return 2 images (skip the one with digest)
        assert len(images) == 2
        assert images[0][1] == "python:3.9-slim-buster"
        assert images[1][1] == "redis:6.2"

        # Clean up
        Path(f.name).unlink()

    def test_parse_dockerfile_case_insensitive(self):
        """Test that FROM statements are matched case-insensitively."""
        content = """
from python:3.9-slim-buster
From node:16-alpine
FROM redis:6.2
        """.strip()

        with tempfile.NamedTemporaryFile(mode='w', suffix='Dockerfile', delete=False) as f:
            f.write(content)
            f.flush()

            images = parse_dockerfile_images(Path(f.name))

        assert len(images) == 3
        assert images[0][1] == "python:3.9-slim-buster"
        assert images[1][1] == "node:16-alpine"
        assert images[2][1] == "redis:6.2"

        # Clean up
        Path(f.name).unlink()


class TestGetImageDigest:
    @patch('subprocess.run')
    def test_get_image_digest_success(self, mock_run):
        """Test successful digest retrieval."""
        mock_manifest = {
            "mediaType": "application/vnd.docker.distribution.manifest.v2+json",
            "config": {
                "digest": "sha256:1234567890abcdef"
            }
        }

        mock_run.return_value = MagicMock(
            stdout='{"mediaType": "application/vnd.docker.distribution.manifest.v2+json", "config": {"digest": "sha256:1234567890abcdef"}}',
            returncode=0
        )

        digest = get_image_digest("python:3.9-slim-buster")
        assert digest == "sha256:1234567890abcdef"

    @patch('subprocess.run')
    def test_get_image_digest_multi_platform(self, mock_run):
        """Test digest retrieval for multi-platform manifest."""
        mock_manifest = {
            "mediaType": "application/vnd.docker.distribution.manifest.list.v2+json",
            "manifests": [
                {"digest": "sha256:abcdef1234567890"},
                {"digest": "sha256:1234567890abcdef"}
            ]
        }

        mock_run.return_value = MagicMock(
            stdout='{"mediaType": "application/vnd.docker.distribution.manifest.list.v2+json", "manifests": [{"digest": "sha256:abcdef1234567890"}, {"digest": "sha256:1234567890abcdef"}]}',
            returncode=0
        )

        digest = get_image_digest("python:3.9-slim-buster")
        assert digest == "sha256:abcdef1234567890"

    @patch('subprocess.run')
    def test_get_image_digest_failure(self, mock_run):
        """Test digest retrieval failure."""
        mock_run.side_effect = subprocess.CalledProcessError(1, 'docker')

        digest = get_image_digest("nonexistent:image")
        assert digest is None


class TestFindDockerfiles:
    def test_find_dockerfiles_in_directory(self):
        """Test finding Dockerfiles in a directory."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir_path = Path(tmpdir)

            # Create various Dockerfile patterns
            (tmpdir_path / "Dockerfile").touch()
            (tmpdir_path / "Dockerfile.prod").touch()
            (tmpdir_path / "app.dockerfile").touch()
            (tmpdir_path / "subdir").mkdir()
            (tmpdir_path / "subdir" / "Dockerfile").touch()

            dockerfiles = find_dockerfiles(tmpdir_path)

            assert len(dockerfiles) == 4
            dockerfile_names = [df.name for df in dockerfiles]
            assert "Dockerfile" in dockerfile_names
            assert "Dockerfile.prod" in dockerfile_names
            assert "app.dockerfile" in dockerfile_names


class TestPinDockerfileImages:
    @patch('src.pin_dockerfile.main.get_image_digest')
    def test_pin_dockerfile_images_dry_run(self, mock_get_digest):
        """Test pinning images in dry run mode."""
        mock_get_digest.return_value = "sha256:1234567890abcdef"

        content = """
FROM python:3.9-slim-buster
WORKDIR /app
COPY . .
        """.strip()

        with tempfile.NamedTemporaryFile(mode='w', suffix='Dockerfile', delete=False) as f:
            f.write(content)
            f.flush()

            # Dry run should not modify the file
            result = pin_dockerfile_images(Path(f.name), dry_run=True)

            # Read the file to ensure it wasn't modified
            with open(f.name, 'r') as read_f:
                file_content = read_f.read()

        assert result is True
        assert file_content == content  # File should be unchanged
        assert mock_get_digest.called

        # Clean up
        Path(f.name).unlink()

    @patch('src.pin_dockerfile.main.get_image_digest')
    def test_pin_dockerfile_images_actual_run(self, mock_get_digest):
        """Test actually pinning images."""
        mock_get_digest.return_value = "sha256:1234567890abcdef"

        content = """FROM python:3.9-slim-buster
WORKDIR /app
COPY . ."""

        with tempfile.NamedTemporaryFile(mode='w', suffix='Dockerfile', delete=False) as f:
            f.write(content)
            f.flush()

            result = pin_dockerfile_images(Path(f.name), dry_run=False)

            # Read the modified file
            with open(f.name, 'r') as read_f:
                modified_content = read_f.read()

        assert result is True
        assert "python@sha256:1234567890abcdef" in modified_content
        assert "python:3.9-slim-buster" not in modified_content

        # Clean up
        Path(f.name).unlink()


if __name__ == "__main__":
    pytest.main([__file__])

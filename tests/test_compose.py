import pytest
import tempfile
import yaml
import json
import subprocess
from pathlib import Path
from unittest.mock import patch, MagicMock

from src.pin_compose.main import (
    extract_images_from_compose,
    update_image_in_compose_data,
    pin_compose_images,
    find_compose_files,
    get_image_digest
)


def test_extract_images_from_compose():
    """Test extracting images from docker-compose data."""
    compose_data = {
        'version': '3.8',
        'services': {
            'web': {
                'image': 'python:3.9-slim',
                'ports': ['8000:8000']
            },
            'db': {
                'image': 'postgres@sha256:abc123',  # Already pinned
                'environment': ['POSTGRES_DB=test']
            },
            'cache': {
                'image': 'redis:6-alpine'
            }
        }
    }
    
    images = extract_images_from_compose(compose_data)
    
    # Should find 2 unpinned images (python and redis)
    assert len(images) == 2
    
    image_names = [img[0] for img in images]
    assert 'python:3.9-slim' in image_names
    assert 'redis:6-alpine' in image_names
    assert 'postgres@sha256:abc123' not in image_names  # Already pinned


def test_update_image_in_compose_data():
    """Test updating image reference in compose data."""
    compose_data = {
        'services': {
            'web': {
                'image': 'python:3.9-slim'
            }
        }
    }
    
    path = ['services', 'web', 'image']
    new_image = 'python@sha256:def456'
    
    updated_data = update_image_in_compose_data(compose_data, path, new_image)
    
    assert updated_data['services']['web']['image'] == 'python@sha256:def456'


def test_find_compose_files():
    """Test finding docker-compose files in directory."""
    with tempfile.TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir)
        
        # Create some test files
        (temp_path / 'docker-compose.yml').touch()
        (temp_path / 'docker-compose.prod.yml').touch()
        (temp_path / 'compose.yaml').touch()
        (temp_path / 'not-a-compose.txt').touch()
        
        # Create subdirectory with compose file
        sub_dir = temp_path / 'subdir'
        sub_dir.mkdir()
        (sub_dir / 'docker-compose.dev.yml').touch()
        
        compose_files = find_compose_files(temp_path)
        
        assert len(compose_files) == 4
        file_names = [f.name for f in compose_files]
        assert 'docker-compose.yml' in file_names
        assert 'docker-compose.prod.yml' in file_names
        assert 'compose.yaml' in file_names
        assert 'docker-compose.dev.yml' in file_names
        assert 'not-a-compose.txt' not in file_names


@patch('src.pin_compose.main.get_image_digest')
def test_pin_compose_images_dry_run(mock_get_digest):
    """Test pinning compose images in dry run mode."""
    mock_get_digest.return_value = 'sha256:abc123'
    
    compose_content = {
        'version': '3.8',
        'services': {
            'web': {
                'image': 'python:3.9-slim'
            }
        }
    }
    
    with tempfile.NamedTemporaryFile(mode='w', suffix='.yml', delete=False) as f:
        yaml.dump(compose_content, f)
        compose_path = Path(f.name)
    
    try:
        # Test dry run
        result = pin_compose_images(compose_path, dry_run=True)
        assert result is True
        
        # File should not be modified
        with open(compose_path, 'r') as f:
            data = yaml.safe_load(f)
        
        assert data['services']['web']['image'] == 'python:3.9-slim'
        
    finally:
        compose_path.unlink()


@patch('src.pin_compose.main.get_image_digest')
def test_pin_compose_images_actual(mock_get_digest):
    """Test actually pinning compose images."""
    mock_get_digest.return_value = 'sha256:abc123'
    
    compose_content = {
        'version': '3.8',
        'services': {
            'web': {
                'image': 'python:3.9-slim'
            }
        }
    }
    
    with tempfile.NamedTemporaryFile(mode='w', suffix='.yml', delete=False) as f:
        yaml.dump(compose_content, f)
        compose_path = Path(f.name)
    
    try:
        # Test actual pinning
        result = pin_compose_images(compose_path, dry_run=False)
        assert result is True
        
        # File should be modified
        with open(compose_path, 'r') as f:
            data = yaml.safe_load(f)
        
        assert data['services']['web']['image'] == 'python@sha256:abc123'
        
    finally:
        compose_path.unlink()


@patch('subprocess.run')
def test_get_image_digest_success(mock_run):
    """Test successful digest retrieval."""
    # Mock the docker manifest inspect command
    mock_result = MagicMock()
    mock_result.stdout = json.dumps({
        'config': {
            'digest': 'sha256:abc123def456'
        }
    })
    mock_run.return_value = mock_result
    
    digest = get_image_digest('python:3.9-slim')
    assert digest == 'sha256:abc123def456'


@patch('subprocess.run')
def test_get_image_digest_failure(mock_run):
    """Test digest retrieval failure."""
    mock_run.side_effect = subprocess.CalledProcessError(1, 'docker')
    
    digest = get_image_digest('nonexistent:image')
    assert digest is None
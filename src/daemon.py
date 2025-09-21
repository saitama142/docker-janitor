
import time
import docker
from datetime import datetime, timedelta, timezone
import logging
import os
import json
import fnmatch
from pathlib import Path

# Try relative imports first, fall back to absolute imports
try:
    from . import config
except ImportError:
    import config

def setup_logging():
    """Setup logging with fallback options if main log file is not accessible."""
    cfg = config.load_config()
    log_file = cfg.get("log_file", "/var/log/docker-janitor.log")
    log_level = cfg.get("log_level", "INFO")
    fallback_log_file = os.path.expanduser("~/.docker-janitor.log")
    
    # Convert string log level to logging constant
    numeric_level = getattr(logging, log_level.upper(), logging.INFO)
    
    # Try to create log directory if it doesn't exist
    try:
        os.makedirs(os.path.dirname(log_file), exist_ok=True)
    except PermissionError:
        pass
    
    handlers = []
    
    # Try primary log file location
    try:
        from logging.handlers import RotatingFileHandler
        # Use rotating file handler for better log management
        file_handler = RotatingFileHandler(
            log_file, 
            maxBytes=10*1024*1024,  # 10MB
            backupCount=5
        )
        handlers.append(file_handler)
    except PermissionError:
        try:
            # Fallback to user home directory
            file_handler = RotatingFileHandler(
                fallback_log_file,
                maxBytes=10*1024*1024,  # 10MB
                backupCount=5
            )
            handlers.append(file_handler)
        except Exception:
            # If all else fails, just use console
            pass
    except ImportError:
        # Fallback to basic FileHandler if RotatingFileHandler not available
        try:
            handlers.append(logging.FileHandler(log_file))
        except PermissionError:
            try:
                handlers.append(logging.FileHandler(fallback_log_file))
            except Exception:
                pass
    
    # Always add console handler for immediate feedback
    console_handler = logging.StreamHandler()
    console_handler.setLevel(numeric_level)
    handlers.append(console_handler)
    
    # Configure logging
    logging.basicConfig(
        level=numeric_level,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        handlers=handlers,
        force=True  # Override any existing configuration
    )
    
    return logging.getLogger(__name__)

# Initialize logger
logger = setup_logging()

def should_exclude_image(image, exclusion_patterns):
    """Check if an image should be excluded based on patterns."""
    if not exclusion_patterns:
        return False
    
    # Check against image tags (handle cases where image.tags might be None or empty)
    tags = image.tags or []
    for tag in tags:
        for pattern in exclusion_patterns:
            if fnmatch.fnmatch(tag, pattern):
                return True
    
    # Check against image ID
    for pattern in exclusion_patterns:
        if fnmatch.fnmatch(image.short_id, pattern):
            return True
    
    # Always exclude images with 'latest' tag unless explicitly overridden
    if any('latest' in tag for tag in tags):
        logger.debug(f"Excluding image {image.short_id} with 'latest' tag")
        return True
    
    # Exclude images with common production patterns unless explicitly overridden
    production_patterns = ['prod', 'production', 'stable', 'release']
    for tag in tags:
        for prod_pattern in production_patterns:
            if prod_pattern in tag.lower():
                logger.debug(f"Excluding image {image.short_id} with production-like tag: {tag}")
                return True
    
    return False

def backup_image_info(images, backup_file):
    """Backup image information before deletion."""
    backup_data = {
        "timestamp": datetime.now().isoformat(),
        "images": []
    }
    
    for image in images:
        image_info = {
            "id": image.id,
            "short_id": image.short_id,
            "tags": image.tags,
            "created": image.attrs.get('Created', ''),
            "size": image.attrs.get('Size', 0),
            "labels": image.attrs.get('Config', {}).get('Labels') or {}
        }
        backup_data["images"].append(image_info)
    
    try:
        os.makedirs(os.path.dirname(backup_file), exist_ok=True)
        with open(backup_file, 'w') as f:
            json.dump(backup_data, f, indent=2)
        logger.info(f"Backed up {len(images)} image(s) info to {backup_file}")
    except Exception as e:
        logger.error(f"Failed to backup image info: {e}")

def get_unused_images(client, age_threshold_days: int, exclusion_patterns=None):
    """Returns a list of unused images older than the threshold."""
    if exclusion_patterns is None:
        exclusion_patterns = []
        
    try:
        # Get ALL images including dangling ones (these are often the biggest space wasters)
        all_images = client.images.list(all=True)
        containers = client.containers.list(all=True)
    except docker.errors.DockerException as e:
        logger.error(f"Failed to connect to Docker daemon: {e}")
        return []

    # Get image IDs that are actually being used by containers
    used_image_ids = set()
    for container in containers:
        used_image_ids.add(container.image.id)
        # Also add parent image IDs if available
        if hasattr(container.image, 'parent_id') and container.image.parent_id:
            used_image_ids.add(container.image.parent_id)

    unused_images = []
    threshold_date = datetime.now(timezone.utc) - timedelta(days=age_threshold_days)

    for image in all_images:
        # An image is unused if no container is using it
        if image.id not in used_image_ids:
            # Check exclusion patterns
            if should_exclude_image(image, exclusion_patterns):
                logger.info(f"Excluding image {image.short_id} due to exclusion rules")
                continue
                
            # Docker API returns created time in ISO 8601 format
            # Handle various timestamp formats from Docker API
            created_time_str = image.attrs['Created']
            try:
                # Try parsing as-is first (most common case)
                if created_time_str.endswith('Z'):
                    # Replace Z with +00:00 for proper ISO format
                    created_time_str = created_time_str.replace('Z', '+00:00')
                elif '+00:00' in created_time_str and created_time_str.count('+00:00') > 1:
                    # Fix double timezone issue
                    created_time_str = created_time_str.replace('+00:00+00:00', '+00:00')
                
                # Remove nanoseconds if present (keep only microseconds)
                if '.' in created_time_str:
                    date_part, time_part = created_time_str.split('.')
                    if '+' in time_part:
                        time_microseconds, tz_part = time_part.split('+', 1)
                        time_microseconds = time_microseconds[:6]  # Keep only 6 digits (microseconds)
                        created_time_str = f"{date_part}.{time_microseconds}+{tz_part}"
                    elif 'Z' in time_part:
                        time_microseconds = time_part.replace('Z', '')[:6]
                        created_time_str = f"{date_part}.{time_microseconds}+00:00"
                
                created_time = datetime.fromisoformat(created_time_str)
            except ValueError as e:
                logger.warning(f"Failed to parse timestamp '{image.attrs['Created']}' for image {image.short_id}: {e}")
                # Fallback: assume image is new if we can't parse the date
                continue

            if created_time < threshold_date:
                unused_images.append(image)
                
        # Log information about what we found
        image_tags = image.tags if image.tags else ["<dangling>"]
        size_mb = image.attrs.get('Size', 0) / (1024 * 1024)
        if image.id in used_image_ids:
            logger.debug(f"Keeping in-use image {image.short_id} with tags: {image_tags} (Size: {size_mb:.2f} MB)")
        elif created_time >= threshold_date:
            logger.debug(f"Keeping recent image {image.short_id} with tags: {image_tags} (Size: {size_mb:.2f} MB)")

    logger.info(f"Found {len(unused_images)} unused images out of {len(all_images)} total images")

    return unused_images

def cleanup_images(dry_run=None):
    """Performs the image cleanup process."""
    logger.info("Starting Docker image cleanup cycle.")
    cfg = config.load_config()
    age_threshold = cfg.get("image_age_threshold_days", 30)
    exclusion_patterns = cfg.get("excluded_image_patterns", [])
    backup_enabled = cfg.get("backup_enabled", True)
    backup_file = cfg.get("backup_file", "/var/lib/docker-janitor/backup.json")
    
    # Override dry_run from config if not explicitly provided
    if dry_run is None:
        dry_run = cfg.get("dry_run_mode", False)

    try:
        client = docker.from_env()
        client.ping() # Verify connection
    except docker.errors.DockerException as e:
        error_msg = str(e)
        if "Permission denied" in error_msg:
            logger.error("Could not connect to Docker daemon: Permission denied. Please ensure the user is in the 'docker' group.")
            logger.error("To fix this, run: sudo usermod -a -G docker $USER && newgrp docker")
        else:
            logger.error(f"Could not connect to Docker daemon: {e}")
        return
    except Exception as e:
        logger.error(f"Unexpected error connecting to Docker: {e}")
        return

    images_to_delete = get_unused_images(client, age_threshold, exclusion_patterns)

    if not images_to_delete:
        logger.info("No old, unused images to delete.")
        return

    logger.info(f"Found {len(images_to_delete)} images to delete.")
    
    if dry_run:
        logger.info("DRY RUN MODE - No images will actually be deleted:")
        total_size = 0
        for image in images_to_delete:
            tags = image.tags if image.tags else ["<dangling>"]
            size_mb = image.attrs.get('Size', 0) / (1024 * 1024)
            total_size += image.attrs.get('Size', 0)
            created_str = image.attrs.get('Created', 'unknown')
            logger.info(f"Would delete image {image.short_id} with tags: {tags} (Size: {size_mb:.2f} MB, Created: {created_str})")
        total_size_mb = total_size / (1024 * 1024)
        logger.info(f"Total space that would be freed: {total_size_mb:.2f} MB")
        return

    # Backup image info before deletion if enabled
    if backup_enabled:
        backup_image_info(images_to_delete, backup_file)

    for image in images_to_delete:
        try:
            tags = image.tags if image.tags else ["<dangling>"]
            size_mb = image.attrs.get('Size', 0) / (1024 * 1024)
            logger.info(f"Deleting image {image.short_id} with tags: {tags} (Size: {size_mb:.2f} MB)")
            client.images.remove(image.id, force=True) # Force to remove even if tagged
            logger.info(f"Successfully deleted image {image.short_id}")
        except docker.errors.APIError as e:
            logger.error(f"Failed to delete image {image.short_id}: {e}")

def run_daemon():
    """The main loop for the daemon process."""
    logger.info("Docker Janitor daemon started.")
    while True:
        cleanup_images()
        
        cfg = config.load_config()
        sleep_interval = cfg.get("daemon_sleep_interval_seconds", 86400)
        logger.info(f"Sleeping for {sleep_interval} seconds...")
        time.sleep(sleep_interval)

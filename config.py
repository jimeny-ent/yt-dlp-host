import os

# File system
DOWNLOAD_DIR = os.getenv('DOWNLOAD_DIR', '/app/downloads')
TASKS_FILE = os.getenv('TASKS_FILE', 'jsons/tasks.json')
KEYS_FILE = os.getenv('KEYS_FILE', 'jsons/api_keys.json')

# Google Cloud Storage settings
GCS_BUCKET_NAME = os.getenv('GCS_BUCKET_NAME')
USE_GCS = os.getenv('USE_GCS', 'True').lower() == 'true'
SYSTEM_FILES_USE_GCS = False  # Force system files to stay local
JSONS_DIR = os.getenv('JSONS_DIR', 'jsons')  # Directory for system JSON files

# Task management
TASK_CLEANUP_TIME = 10  # minutes
REQUEST_LIMIT = 60 # per TASK_CLEANUP_TIME
MAX_WORKERS = 4

# API key settings
DEFAULT_MEMORY_QUOTA = 5 * 1024 * 1024 * 1024  # 5GB default quota (in bytes)
DEFAULT_MEMORY_QUOTA_RATE = 10  # minutes to rate limit

# Memory control
SIZE_ESTIMATION_BUFFER = 1.10
AVAILABLE_MEMORY = 20 * 1024 * 1024 * 1024  # 20GB

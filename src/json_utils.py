from config import TASKS_FILE, KEYS_FILE, USE_GCS
from src.storage_utils import StorageManager
import os
import json
import logging

logger = logging.getLogger(__name__)
storage_manager = StorageManager()

def load_tasks():
    """Load tasks from either GCS or local storage"""
    try:
        content = storage_manager.get_system_file('tasks.json')
        if content:
            return json.loads(content)
        logger.warning("No tasks found, returning empty dict")
        return {}
    except Exception as e:
        logger.error(f"Error loading tasks: {str(e)}")
        return {}

def save_tasks(tasks):
    """Save tasks to either GCS or local storage"""
    try:
        logger.info("Saving tasks file")
        storage_manager.save_system_file(
            'tasks.json',
            json.dumps(tasks, indent=4)
        )
        logger.info("Tasks saved successfully")
    except Exception as e:
        logger.error(f"Error saving tasks: {str(e)}")
        raise

def load_keys():
    """Load API keys from either GCS or local storage"""
    try:
        content = storage_manager.get_system_file('api_keys.json')
        if content:
            return json.loads(content)
        logger.warning("No API keys found, returning empty dict")
        return {}
    except Exception as e:
        logger.error(f"Error loading keys: {str(e)}")
        return {}

def save_keys(keys):
    """Save API keys to either GCS or local storage"""
    try:
        logger.info("Saving API keys file")
        storage_manager.save_system_file(
            'api_keys.json',
            json.dumps(keys, indent=4)
        )
        logger.info("API keys saved successfully")
    except Exception as e:
        logger.error(f"Error saving keys: {str(e)}")
        raise
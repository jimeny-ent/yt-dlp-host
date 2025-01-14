from config import TASKS_FILE, KEYS_FILE, USE_GCS
from src.storage_utils import StorageManager
import os
import json

storage_manager = StorageManager()

def load_tasks():
    """Load tasks from either GCS or local storage"""
    if USE_GCS:
        try:
            blob = storage_manager.get_file('jsons/tasks.json')
            if blob:
                content = blob.download_as_string()
                return json.loads(content)
            return {}
        except Exception as e:
            print(f"Error loading tasks from GCS: {e}")
            return {}
    else:
        if os.path.exists(TASKS_FILE):
            with open(TASKS_FILE, 'r') as f:
                return json.load(f)
        return {}

def save_tasks(tasks):
    """Save tasks to either GCS or local storage"""
    if USE_GCS:
        try:
            storage_manager.save_task_file(
                'jsons',
                'tasks.json',
                json.dumps(tasks, indent=4)
            )
        except Exception as e:
            print(f"Error saving tasks to GCS: {e}")
    else:
        with open(TASKS_FILE, 'w') as f:
            json.dump(tasks, f, indent=4)

def load_keys():
    """Load API keys from either GCS or local storage"""
    if USE_GCS:
        try:
            blob = storage_manager.get_file('jsons/api_keys.json')
            if blob:
                content = blob.download_as_string()
                return json.loads(content)
            return {}
        except Exception as e:
            print(f"Error loading keys from GCS: {e}")
            return {}
    else:
        if os.path.exists(KEYS_FILE):
            with open(KEYS_FILE, 'r') as f:
                return json.load(f)
        return {}

def save_keys(keys):
    """Save API keys to either GCS or local storage"""
    if USE_GCS:
        try:
            storage_manager.save_task_file(
                'jsons',
                'api_keys.json',
                json.dumps(keys, indent=4)
            )
        except Exception as e:
            print(f"Error saving keys to GCS: {e}")
    else:
        with open(KEYS_FILE, 'w') as f:
            json.dump(keys, f, indent=4)
import logging
import os
from typing import Any

import requests


logger = logging.getLogger(__name__)
PARSEHUB_PROJECTS_URL = 'https://www.parsehub.com/api/v2/projects'


def fetch_all_projects(api_key: str) -> list[dict[str, Any]]:
    if not api_key:
        raise ValueError('API key cannot be empty')

    projects: list[dict[str, Any]] = []
    offset = 0
    page_size = max(20, min(int(os.getenv('PARSEHUB_PROJECTS_PAGE_SIZE', '100')), 500))

    while True:
        response = requests.get(
            PARSEHUB_PROJECTS_URL,
            params={'api_key': api_key, 'offset': offset, 'limit': page_size},
            timeout=30,
        )
        response.raise_for_status()
        payload = response.json()
        page_projects = payload.get('projects', [])
        total_projects = payload.get('total_projects', len(page_projects))
        projects.extend(page_projects)
        logger.info('Fetched %s/%s ParseHub projects', len(projects), total_projects)
        if not page_projects or len(projects) >= total_projects:
            break
        offset += len(page_projects)

    return projects

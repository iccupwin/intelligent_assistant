import os
import logging
import requests
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Union, Any

from django.conf import settings
from django.utils import timezone
from django.core.cache import cache
from django.core.exceptions import ValidationError

logger = logging.getLogger(__name__)


class PlanfixAPIError(Exception):
    """Custom exception for Planfix API errors."""
    pass


class PlanfixAPI:
    """Class to interact with the Planfix API."""
    
    def __init__(self, api_key=None, account_id=None, user_id=None, user_api_key=None):
        self.api_url = getattr(settings, 'PLANFIX_API_URL', 'https://deventky.planfix.com/rest')
        self.api_key = api_key or getattr(settings, 'PLANFIX_API_TOKEN', None)
        self.account_id = account_id or getattr(settings, 'PLANFIX_ACCOUNT_ID', None)
        self.user_id = user_id or getattr(settings, 'PLANFIX_USER_ID', None)
        self.user_api_key = user_api_key or getattr(settings, 'PLANFIX_USER_API_KEY', None)
        
        # Validate required settings
        if not all([self.api_key, self.account_id]):
            raise ValidationError("Missing required Planfix API configuration.")
    
    def _get_headers(self) -> Dict[str, str]:
        """Get default headers for API requests."""
        headers = {
            'Content-Type': 'application/json',
            'Accept': 'application/json',
            'Authorization': f'Bearer {self.api_key}'
        }
        return headers
    
    def _make_request(self, method: str, endpoint: str, params: Dict = None, data: Dict = None) -> Dict:
        """Make a request to the Planfix API."""
        # Формируем URL без параметров
        base_url = self.api_url.rstrip('/')
        if not base_url.startswith('https://'):
            base_url = f"https://{base_url}"
        url = f"{base_url}/{endpoint}"
        
        headers = self._get_headers()
        
        # Формируем JSON запрос
        if data:
            request_data = data
            logger.debug(f"Request URL: {url}")
            logger.debug(f"Request headers: {headers}")
            logger.debug(f"Request JSON: {request_data}")
        
        try:
            # Создаем сессию для более точного контроля над запросом
            session = requests.Session()
            
            # Убираем params из URL, так как они передаются в JSON
            response = session.request(
                method=method,
                url=url,
                headers=headers,
                json=request_data if data else None,
                params=None,  # Явно указываем, что параметров в URL быть не должно
                allow_redirects=True  # Разрешаем следовать за перенаправлениями
            )
            
            logger.debug(f"Response status: {response.status_code}")
            logger.debug(f"Response headers: {response.headers}")
            logger.debug(f"Final URL: {response.url}")  # Добавляем логирование финального URL
            
            # Проверяем, что ответ не пустой
            if not response.content:
                logger.error("Empty response received")
                raise PlanfixAPIError("Empty response received from Planfix API")
            
            # Логируем содержимое ответа
            logger.debug(f"Response content: {response.content}")
            
            try:
                return response.json()
            except ValueError as e:
                logger.error(f"Failed to parse JSON response: {str(e)}")
                logger.error(f"Response content: {response.content}")
                raise PlanfixAPIError(f"Invalid JSON response from Planfix API: {str(e)}")
            
        except requests.exceptions.RequestException as e:
            logger.error(f"Planfix API error: {str(e)}")
            if hasattr(e, 'response') and e.response is not None:
                try:
                    error_data = e.response.json()
                    error_message = error_data.get('message', str(e))
                except ValueError:
                    error_message = str(e)
            else:
                error_message = str(e)
                
            raise PlanfixAPIError(f"Error communicating with Planfix API: {error_message}")
        finally:
            session.close()
    
    # Tasks related methods
    def get_tasks(self, filters: Dict = None, limit: int = 100, offset: int = 0) -> Dict:
        """
        Get tasks from Planfix with optional filtering.
        
        Args:
            filters: Dictionary containing filter parameters
            limit: Maximum number of tasks to return
            offset: Offset for pagination
            
        Returns:
            Dictionary containing tasks data
        """
        cache_key = f"planfix_tasks_{hash(frozenset({'offset': offset, 'limit': limit}.items()))}"
        cached_data = cache.get(cache_key)
        if cached_data:
            return cached_data
        
        # Формируем данные запроса в соответствии с документацией API
        data = {
            "offset": offset,
            "pageSize": limit,
            "fields": "id,name,status,project,startDateTime,endDateTime,description,assignees,assigner,priority,resultChecking,parent,counterparty,dateTime,hasStartDate,hasEndDate,hasStartTime,hasEndTime,dateOfLastUpdate,duration,durationUnit,durationType,inFavorites,isSummary,isSequential,participants,auditors,isDeleted"
        }
        
        # Если есть дополнительные фильтры, добавляем их
        if filters:
            data.update(filters)
        
        logger.debug(f"Getting tasks with data: {data}")
        result = self._make_request('POST', 'task/list', data=data)
        
        # Проверяем структуру ответа
        if not isinstance(result, dict):
            logger.error(f"Unexpected response type: {type(result)}")
            logger.error(f"Response content: {result}")
            return {"tasks": []}
            
        # Проверяем наличие ключа tasks
        if 'tasks' not in result:
            logger.error(f"No 'tasks' key in response: {result}")
            return {"tasks": []}
            
        # Проверяем, что tasks это список
        tasks = result.get('tasks', [])
        if not isinstance(tasks, list):
            logger.error(f"Tasks is not a list: {type(tasks)}")
            return {"tasks": []}
            
        # Проверяем каждый элемент в списке
        valid_tasks = []
        for task in tasks:
            if isinstance(task, dict):
                # Проверяем обязательные поля
                if 'id' not in task:
                    logger.error(f"Task missing required field 'id': {task}")
                    continue
                valid_tasks.append(task)
            else:
                logger.error(f"Task is not a dictionary: {task}")
                
        result['tasks'] = valid_tasks
        
        # Cache results for 5 minutes
        cache.set(cache_key, result, 300)
        return result
    
    def get_task(self, task_id: Union[str, int]) -> Dict:
        """
        Get a specific task by ID.
        
        Args:
            task_id: ID of the task to retrieve
            
        Returns:
            Dictionary containing task data
        """
        cache_key = f"planfix_task_{task_id}"
        cached_data = cache.get(cache_key)
        if cached_data:
            return cached_data
        
        result = self._make_request('GET', f'tasks/{task_id}')
        
        # Cache results for 5 minutes
        cache.set(cache_key, result, 300)
        return result
    
    def get_task_comments(self, task_id: Union[str, int]) -> List[Dict]:
        """
        Get comments for a specific task.
        
        Args:
            task_id: ID of the task
            
        Returns:
            List of comments
        """
        cache_key = f"planfix_task_comments_{task_id}"
        cached_data = cache.get(cache_key)
        if cached_data:
            return cached_data
        
        result = self._make_request('GET', f'tasks/{task_id}/comments')
        comments = result.get('comments', [])
        
        # Cache results for 5 minutes
        cache.set(cache_key, comments, 300)
        return comments
    
    def get_task_attachments(self, task_id: Union[str, int]) -> List[Dict]:
        """
        Get attachments for a specific task.
        
        Args:
            task_id: ID of the task
            
        Returns:
            List of attachments
        """
        cache_key = f"planfix_task_attachments_{task_id}"
        cached_data = cache.get(cache_key)
        if cached_data:
            return cached_data
        
        result = self._make_request('GET', f'tasks/{task_id}/files')
        attachments = result.get('files', [])
        
        # Cache results for 5 minutes
        cache.set(cache_key, attachments, 300)
        return attachments
    
    def create_task(self, task_data: Dict) -> Dict:
        """
        Create a new task.
        
        Args:
            task_data: Dictionary containing task data
            
        Returns:
            Dictionary containing created task data
        """
        return self._make_request('POST', 'tasks', data=task_data)
    
    def update_task(self, task_id: Union[str, int], task_data: Dict) -> Dict:
        """
        Update an existing task.
        
        Args:
            task_id: ID of the task to update
            task_data: Dictionary containing task data to update
            
        Returns:
            Dictionary containing updated task data
        """
        return self._make_request('PUT', f'tasks/{task_id}', data=task_data)
    
    def add_task_comment(self, task_id: Union[str, int], comment_data: Dict) -> Dict:
        """
        Add a comment to a task.
        
        Args:
            task_id: ID of the task
            comment_data: Dictionary containing comment data
            
        Returns:
            Dictionary containing created comment data
        """
        return self._make_request('POST', f'tasks/{task_id}/comments', data=comment_data)
    
    # Projects related methods
    def get_projects(self, filters: Dict = None, limit: int = 100, offset: int = 0) -> Dict:
        """
        Get projects from Planfix with optional filtering.
        
        Args:
            filters: Dictionary containing filter parameters
            limit: Maximum number of projects to return
            offset: Offset for pagination
            
        Returns:
            Dictionary containing projects data
        """
        cache_key = f"planfix_projects_{hash(frozenset({'offset': offset, 'limit': limit}.items()))}"
        cached_data = cache.get(cache_key)
        if cached_data:
            return cached_data
        
        # Формируем данные запроса в точном формате, который работал в прошлом проекте
        data = {
            "offset": offset,
            "pageSize": limit,
            "filters": [
                {
                    "type": 5001,
                    "operator": "equal",
                    "value": ""
                }
            ],
            "fields": "id,name,description"
        }
        
        # Если есть дополнительные фильтры, добавляем их
        if filters:
            data.update(filters)
        
        logger.debug(f"Getting projects with data: {data}")
        result = self._make_request('POST', 'project/list', data=data)
        
        # Cache results for 10 minutes
        cache.set(cache_key, result, 600)
        return result
    
    def get_project(self, project_id: Union[str, int]) -> Dict:
        """
        Get a specific project by ID.
        
        Args:
            project_id: ID of the project to retrieve
            
        Returns:
            Dictionary containing project data
        """
        cache_key = f"planfix_project_{project_id}"
        cached_data = cache.get(cache_key)
        if cached_data:
            return cached_data
        
        result = self._make_request('GET', f'projects/{project_id}')
        
        # Cache results for 10 minutes
        cache.set(cache_key, result, 600)
        return result
    
    # Employees related methods
    def get_employees(self, filters: Dict = None, limit: int = 100, offset: int = 0) -> Dict:
        """
        Get employees from Planfix with optional filtering.
        
        Args:
            filters: Dictionary containing filter parameters
            limit: Maximum number of employees to return
            offset: Offset for pagination
            
        Returns:
            Dictionary containing employees data
        """
        cache_key = f"planfix_employees_{hash(frozenset({'offset': offset, 'limit': limit}.items()))}"
        cached_data = cache.get(cache_key)
        if cached_data:
            return cached_data
        
        # Формируем данные запроса в точном формате, который работал в прошлом проекте
        data = {
            "offset": offset,
            "pageSize": limit,
            "fields": "id,name,midname,lastname"
        }
        
        # Если есть дополнительные фильтры, добавляем их
        if filters:
            data.update(filters)
        
        logger.debug(f"Getting employees with data: {data}")
        result = self._make_request('POST', 'user/list', data=data)
        
        # Cache results for 5 minutes
        cache.set(cache_key, result, 300)
        return result
    
    def get_employee(self, employee_id: Union[str, int]) -> Dict:
        """
        Get a specific employee by ID.
        
        Args:
            employee_id: ID of the employee to retrieve
            
        Returns:
            Dictionary containing employee data
        """
        cache_key = f"planfix_employee_{employee_id}"
        cached_data = cache.get(cache_key)
        if cached_data:
            return cached_data
        
        result = self._make_request('GET', f'users/{employee_id}')
        
        # Cache results for 1 hour
        cache.set(cache_key, result, 3600)
        return result
    
    # Status related methods
    def get_task_statuses(self) -> List[Dict]:
        """
        Get all task statuses.
        
        Returns:
            List of task statuses
        """
        cache_key = "planfix_task_statuses"
        cached_data = cache.get(cache_key)
        if cached_data:
            return cached_data
        
        result = self._make_request('GET', 'task/statuses')
        statuses = result.get('statuses', [])
        
        # Cache results for 1 day (statuses rarely change)
        cache.set(cache_key, statuses, 86400)
        return statuses
    
    def get_project_statuses(self) -> List[Dict]:
        """
        Get all project statuses.
        
        Returns:
            List of project statuses
        """
        cache_key = "planfix_project_statuses"
        cached_data = cache.get(cache_key)
        if cached_data:
            return cached_data
        
        result = self._make_request('GET', 'project/statuses')
        statuses = result.get('statuses', [])
        
        # Cache results for 1 day (statuses rarely change)
        cache.set(cache_key, statuses, 86400)
        return statuses
    
    # Custom fields
    def get_task_custom_fields(self) -> List[Dict]:
        """
        Get all task custom fields.
        
        Returns:
            List of task custom fields
        """
        cache_key = "planfix_task_custom_fields"
        cached_data = cache.get(cache_key)
        if cached_data:
            return cached_data
        
        result = self._make_request('GET', 'task/fields')
        fields = result.get('fields', [])
        
        # Cache results for 1 day (custom fields rarely change)
        cache.set(cache_key, fields, 86400)
        return fields
    
    def get_project_custom_fields(self) -> List[Dict]:
        """
        Get all project custom fields.
        
        Returns:
            List of project custom fields
        """
        cache_key = "planfix_project_custom_fields"
        cached_data = cache.get(cache_key)
        if cached_data:
            return cached_data
        
        result = self._make_request('GET', 'project/fields')
        fields = result.get('fields', [])
        
        # Cache results for 1 day (custom fields rarely change)
        cache.set(cache_key, fields, 86400)
        return fields
    
    # Files
    def download_file(self, file_id: Union[str, int]) -> bytes:
        """
        Download a file by ID.
        
        Args:
            file_id: ID of the file to download
            
        Returns:
            File content as bytes
        """
        url = f"{self.api_url}/files/{file_id}/download"
        headers = self._get_headers()
        
        try:
            response = requests.get(url, headers=headers)
            response.raise_for_status()
            return response.content
        except requests.exceptions.RequestException as e:
            logger.error(f"Error downloading file: {str(e)}")
            raise PlanfixAPIError(f"Error downloading file: {str(e)}")
    
    # Helper methods for data synchronization
    def sync_all_data(self) -> Dict:
        """
        Synchronize all data from Planfix.
        
        Returns:
            Dictionary with statistics about synchronized data
        """
        stats = {
            'tasks': 0,
            'projects': 0,
            'employees': 0,
            'comments': 0,
            'attachments': 0,
            'errors': []
        }
        
        try:
            # Sync projects
            projects_data = self.get_projects(limit=500)
            logger.debug(f"Projects data: {projects_data}")
            projects = projects_data.get('projects', [])
            stats['projects'] = len(projects)
            
            # Sync employees
            employees_data = self.get_employees(limit=500)
            logger.debug(f"Employees data: {employees_data}")
            employees = employees_data.get('users', [])
            stats['employees'] = len(employees)
            
            # Sync tasks (paginated)
            offset = 0
            limit = 100
            while True:
                tasks_data = self.get_tasks(limit=limit, offset=offset)
                logger.debug(f"Tasks data: {tasks_data}")
                
                # Проверяем структуру ответа
                if not isinstance(tasks_data, dict):
                    logger.error(f"Unexpected tasks data type: {type(tasks_data)}")
                    stats['errors'].append(f"Unexpected tasks data type: {type(tasks_data)}")
                    break
                
                tasks = tasks_data.get('tasks', [])
                if not tasks:
                    break
                
                logger.debug(f"Processing {len(tasks)} tasks (offset: {offset})")
                stats['tasks'] += len(tasks)
                
                # For each task, sync comments and attachments
                for i, task in enumerate(tasks):
                    try:
                        # Проверяем, что task это словарь
                        if not isinstance(task, dict):
                            logger.error(f"Task {i} is not a dictionary: {task}")
                            continue
                            
                        # Логируем структуру задачи для отладки
                        logger.debug(f"Task {i} structure: {task}")
                        
                        task_id = task.get('id')
                        if not task_id:
                            logger.error(f"Task {i} has no ID: {task}")
                            continue
                        
                        # Sync comments
                        try:
                            comments = self.get_task_comments(task_id)
                            stats['comments'] += len(comments)
                        except Exception as e:
                            logger.error(f"Error getting comments for task {task_id}: {str(e)}")
                            stats['errors'].append(f"Error getting comments for task {task_id}: {str(e)}")
                        
                        # Sync attachments
                        try:
                            attachments = self.get_task_attachments(task_id)
                            stats['attachments'] += len(attachments)
                        except Exception as e:
                            logger.error(f"Error getting attachments for task {task_id}: {str(e)}")
                            stats['errors'].append(f"Error getting attachments for task {task_id}: {str(e)}")
                            
                    except Exception as e:
                        logger.error(f"Error processing task {i}: {str(e)}")
                        stats['errors'].append(f"Error processing task {i}: {str(e)}")
                
                offset += limit
                
                # Safety check to prevent infinite loops
                if offset > 5000:  # Limit to 5000 tasks
                    break
            
            return stats
        except PlanfixAPIError as e:
            logger.error(f"Error during data synchronization: {str(e)}")
            stats['errors'].append(str(e))
            return stats
        except Exception as e:
            logger.error(f"Unexpected error during synchronization: {str(e)}")
            stats['errors'].append(f"Unexpected error: {str(e)}")
            return stats
            
    def get_tasks_due_soon(self, days: int = 7, limit: int = 10) -> List[Dict]:
        """
        Get tasks due in the next X days.
        
        Args:
            days: Number of days to look ahead
            limit: Maximum number of tasks to return
            
        Returns:
            List of tasks
        """
        # Calculate date range
        today = datetime.now().strftime('%Y-%m-%dT00:00:00')
        future_date = (datetime.now() + timedelta(days=days)).strftime('%Y-%m-%dT23:59:59')
        
        # Set up filters
        filters = {
            'deadlineFrom': today,
            'deadlineTo': future_date,
            'status': 'not_done',  # Exclude completed tasks
            'orderBy': 'deadline'  # Order by deadline
        }
        
        # Get tasks
        result = self.get_tasks(filters=filters, limit=limit)
        return result.get('tasks', [])
    
    def get_recent_activity(self, days: int = 7, limit: int = 10) -> Dict:
        """
        Get recent activity (updated tasks and comments).
        
        Args:
            days: Number of days to look back
            limit: Maximum number of items to return
            
        Returns:
            Dictionary with recent tasks and comments
        """
        past_date = (datetime.now() - timedelta(days=days)).strftime('%Y-%m-%dT00:00:00')
        
        # Get recently updated tasks
        task_filters = {
            'updatedAfter': past_date,
            'orderBy': 'updated_at:desc'
        }
        recent_tasks_data = self.get_tasks(filters=task_filters, limit=limit)
        recent_tasks = recent_tasks_data.get('tasks', [])
        
        # Get recent comments (this requires fetching tasks first since Planfix API doesn't 
        # have a direct endpoint for getting comments across all tasks)
        recent_comments = []
        for task in recent_tasks:
            task_id = task.get('id')
            comments = self.get_task_comments(task_id)
            
            # Filter comments by date
            for comment in comments:
                comment_date_str = comment.get('createDateTime')
                if comment_date_str:
                    comment_date = datetime.fromisoformat(comment_date_str.replace('Z', '+00:00'))
                    if comment_date > datetime.now() - timedelta(days=days):
                        # Add task info to comment for context
                        comment['task'] = {
                            'id': task_id,
                            'title': task.get('title')
                        }
                        recent_comments.append(comment)
        
        # Sort comments by date (newest first)
        recent_comments = sorted(
            recent_comments, 
            key=lambda x: x.get('createDateTime', ''), 
            reverse=True
        )[:limit]
        
        return {
            'tasks': recent_tasks,
            'comments': recent_comments
        }
    
    def get_my_tasks(self, user_id: Union[str, int], limit: int = 10) -> List[Dict]:
        """
        Get tasks assigned to a specific user.
        
        Args:
            user_id: ID of the user
            limit: Maximum number of tasks to return
            
        Returns:
            List of tasks
        """
        # Set up filters to get tasks assigned to the user
        filters = {
            'assignees': user_id,
            'status': 'not_done',  # Exclude completed tasks
            'orderBy': 'deadline'  # Order by deadline
        }
        
        # Get tasks
        result = self.get_tasks(filters=filters, limit=limit)
        return result.get('tasks', [])
    
    def get_user_stats(self, user_id: Union[str, int]) -> Dict:
        """
        Get statistics for a specific user.
        
        Args:
            user_id: ID of the user
            
        Returns:
            Dictionary with user statistics
        """
        # Get tasks assigned to the user
        all_tasks = self.get_my_tasks(user_id, limit=1000)
        
        # Calculate statistics
        total_tasks = len(all_tasks)
        overdue_tasks = 0
        due_soon_tasks = 0
        no_deadline_tasks = 0
        
        today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        
        for task in all_tasks:
            deadline_str = task.get('deadline')
            if deadline_str:
                deadline = datetime.fromisoformat(deadline_str.replace('Z', '+00:00'))
                if deadline < today:
                    overdue_tasks += 1
                elif deadline < today + timedelta(days=7):
                    due_soon_tasks += 1
            else:
                no_deadline_tasks += 1
        
        # Get projects where user is responsible
        projects_data = self.get_projects(limit=1000)
        projects = projects_data.get('projects', [])
        
        responsible_projects = []
        for project in projects:
            responsible_persons = project.get('responsibleEmployees', [])
            for person in responsible_persons:
                if str(person.get('id')) == str(user_id):
                    responsible_projects.append(project)
                    break
        
        return {
            'total_tasks': total_tasks,
            'overdue_tasks': overdue_tasks,
            'due_soon_tasks': due_soon_tasks,
            'no_deadline_tasks': no_deadline_tasks,
            'responsible_projects': len(responsible_projects)
        }
    
    def search(self, query: str, entity_type: str = None, limit: int = 20) -> Dict:
        """
        Search for Planfix entities.
        
        Args:
            query: Search query
            entity_type: Type of entity to search for (tasks, projects, employees)
            limit: Maximum number of results to return
            
        Returns:
            Dictionary with search results
        """
        results = {
            'tasks': [],
            'projects': [],
            'employees': []
        }
        
        # If entity_type is specified, only search for that type
        if entity_type and entity_type in results:
            if entity_type == 'tasks':
                task_filters = {
                    'search': query,
                    'limit': limit
                }
                tasks_data = self.get_tasks(filters=task_filters)
                results['tasks'] = tasks_data.get('tasks', [])
            elif entity_type == 'projects':
                project_filters = {
                    'search': query,
                    'limit': limit
                }
                projects_data = self.get_projects(filters=project_filters)
                results['projects'] = projects_data.get('projects', [])
            elif entity_type == 'employees':
                employee_filters = {
                    'search': query,
                    'limit': limit
                }
                employees_data = self.get_employees(filters=employee_filters)
                results['employees'] = employees_data.get('users', [])
        else:
            # Search all entity types
            task_filters = {
                'search': query,
                'limit': limit
            }
            tasks_data = self.get_tasks(filters=task_filters)
            results['tasks'] = tasks_data.get('tasks', [])
            
            project_filters = {
                'search': query,
                'limit': limit
            }
            projects_data = self.get_projects(filters=project_filters)
            results['projects'] = projects_data.get('projects', [])
            
            employee_filters = {
                'search': query,
                'limit': limit
            }
            employees_data = self.get_employees(filters=employee_filters)
            results['employees'] = employees_data.get('users', [])
        
        return results
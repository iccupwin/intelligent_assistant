import time
import logging
from django.core.management.base import BaseCommand
from django.conf import settings
from django.utils import timezone
from django.db import transaction
from django.db.utils import IntegrityError

from core.planfix_api import PlanfixAPI, PlanfixAPIError
from core.models import (
    User, Task, Project, Comment, Attachment, 
    LogEntry, VectorDBMetadata
)

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = 'Synchronize data from Planfix API'
    
    def add_arguments(self, parser):
        parser.add_argument(
            '--full',
            action='store_true',
            help='Perform a full synchronization (ignore timestamps)',
        )
        parser.add_argument(
            '--tasks-only',
            action='store_true',
            help='Synchronize only tasks',
        )
        parser.add_argument(
            '--projects-only',
            action='store_true',
            help='Synchronize only projects',
        )
        parser.add_argument(
            '--users-only',
            action='store_true',
            help='Synchronize only users/employees',
        )
        parser.add_argument(
            '--limit',
            type=int,
            default=None,
            help='Limit the number of items to synchronize',
        )
    
    def handle(self, *args, **options):
        start_time = time.time()
        self.stdout.write(self.style.SUCCESS('Starting Planfix data synchronization...'))
        
        # Create log entry for start
        LogEntry.objects.create(
            level='INFO',
            source='sync_planfix_data',
            message='Starting Planfix data synchronization',
            metadata={
                'options': {k: v for k, v in options.items() if k != '_'}
            }
        )
        
        try:
            # Initialize Planfix API
            api = PlanfixAPI()
            
            # Determine what to sync
            sync_all = not (options['tasks_only'] or options['projects_only'] or options['users_only'])
            
            # Sync users/employees
            if sync_all or options['users_only']:
                self.sync_employees(api, options['full'], options['limit'])
            
            # Sync projects
            if sync_all or options['projects_only']:
                self.sync_projects(api, options['full'], options['limit'])
            
            # Sync tasks
            if sync_all or options['tasks_only']:
                self.sync_tasks(api, options['full'], options['limit'])
            
            end_time = time.time()
            duration = round(end_time - start_time, 2)
            
            # Create log entry for completion
            LogEntry.objects.create(
                level='INFO',
                source='sync_planfix_data',
                message='Planfix data synchronization completed successfully',
                metadata={
                    'duration_seconds': duration
                }
            )
            
            self.stdout.write(
                self.style.SUCCESS(f'Planfix data synchronization completed in {duration} seconds')
            )
            
        except Exception as e:
            # Log error
            LogEntry.objects.create(
                level='ERROR',
                source='sync_planfix_data',
                message=f'Error during Planfix data synchronization: {str(e)}',
                metadata={
                    'exception_type': str(type(e).__name__)
                }
            )
            
            self.stdout.write(
                self.style.ERROR(f'Error during Planfix data synchronization: {str(e)}')
            )
    
    def sync_employees(self, api, full_sync=False, limit=None):
        """Synchronize employees/users from Planfix."""
        self.stdout.write('Synchronizing employees...')
        
        try:
            # Get all employees from Planfix
            employees_data = api.get_employees(limit=limit or 500)
            employees = employees_data.get('users', [])
            
            self.stdout.write(f'Found {len(employees)} employees in Planfix')
            
            # Process each employee
            for employee in employees:
                try:
                    planfix_id = str(employee.get('id'))
                    
                    # Try to find existing user by Planfix ID
                    user = User.objects.filter(planfix_id=planfix_id).first()
                    
                    # Extract employee data
                    email = employee.get('email', '')
                    username = email or f"planfix_{planfix_id}"
                    first_name = employee.get('firstName', '')
                    last_name = employee.get('lastName', '')
                    is_active = not employee.get('isArchive', False)
                    
                    # Determine role based on Planfix role
                    role = 'collaborator'  # Default role
                    
                    # Get additional details if available
                    employee_details = api.get_employee(planfix_id)
                    position = employee_details.get('position', '')
                    
                    if user:
                        # Update existing user
                        user.username = username
                        user.email = email
                        user.first_name = first_name
                        user.last_name = last_name
                        user.is_active = is_active
                        # Only update role if not already set to a higher privilege
                        if user.role not in ['administrator', 'manager']:
                            user.role = role
                        user.save()
                    else:
                        # Create new user
                        user = User.objects.create(
                            planfix_id=planfix_id,
                            username=username,
                            email=email,
                            first_name=first_name,
                            last_name=last_name,
                            is_active=is_active,
                            role=role
                        )
                        
                        # Set a random password (user will need to reset it)
                        user.set_unusable_password()
                        user.save()
                    
                    self.stdout.write(f'Synchronized employee: {first_name} {last_name}')
                    
                except Exception as e:
                    self.stdout.write(
                        self.style.WARNING(f'Error processing employee {employee.get("id")}: {str(e)}')
                    )
            
            self.stdout.write(self.style.SUCCESS('Employee synchronization completed'))
            
        except Exception as e:
            self.stdout.write(
                self.style.ERROR(f'Error synchronizing employees: {str(e)}')
            )
            raise
    
    def sync_projects(self, api, full_sync=False, limit=None):
        """Synchronize projects from Planfix."""
        self.stdout.write('Synchronizing projects...')
        
        try:
            # Get all projects from Planfix
            projects_data = api.get_projects(limit=limit or 500)
            projects = projects_data.get('projects', [])
            
            self.stdout.write(f'Found {len(projects)} projects in Planfix')
            
            # Get project statuses for reference
            project_statuses = api.get_project_statuses()
            status_map = {status['id']: status['name'] for status in project_statuses}
            
            # Get custom fields for reference
            custom_fields = api.get_project_custom_fields()
            custom_field_map = {field['id']: field['name'] for field in custom_fields}
            
            # Process each project
            for project_data in projects:
                try:
                    with transaction.atomic():
                        planfix_id = str(project_data.get('id'))
                        
                        # Try to find existing project by Planfix ID
                        project = Project.objects.filter(planfix_id=planfix_id).first()
                        
                        # Get detailed project data
                        project_details = api.get_project(planfix_id)
                        
                        # Extract project data
                        name = project_details.get('name', '')
                        description = project_details.get('description', '')
                        status_id = project_details.get('status', {}).get('id')
                        status = status_map.get(status_id, 'Unknown')
                        
                        # Parse created date
                        created_date_str = project_details.get('createDateTime')
                        created_date = timezone.now()
                        if created_date_str:
                            try:
                                # Parse ISO format date string
                                created_date = timezone.datetime.fromisoformat(created_date_str.replace('Z', '+00:00'))
                            except ValueError:
                                pass
                        
                        # Extract custom fields
                        custom_fields_data = {}
                        for field in project_details.get('customFields', []):
                            field_id = field.get('id')
                            field_name = custom_field_map.get(field_id, f'field_{field_id}')
                            field_value = field.get('value')
                            if field_value:
                                custom_fields_data[field_name] = field_value
                        
                        if project:
                            # Update existing project
                            project.name = name
                            project.description = description
                            project.status = status
                            project.created_date = created_date
                            project.custom_fields = custom_fields_data
                            project.save()
                        else:
                            # Create new project
                            project = Project.objects.create(
                                planfix_id=planfix_id,
                                name=name,
                                description=description,
                                status=status,
                                created_date=created_date,
                                custom_fields=custom_fields_data
                            )
                        
                        # Process responsible persons
                        responsible_persons = []
                        for person_data in project_details.get('responsibleEmployees', []):
                            person_id = str(person_data.get('id'))
                            try:
                                user = User.objects.get(planfix_id=person_id)
                                responsible_persons.append(user)
                            except User.DoesNotExist:
                                pass
                        
                        # Set responsible persons
                        project.responsible_persons.set(responsible_persons)
                        
                        self.stdout.write(f'Synchronized project: {name}')
                
                except Exception as e:
                    self.stdout.write(
                        self.style.WARNING(f'Error processing project {project_data.get("id")}: {str(e)}')
                    )
            
            self.stdout.write(self.style.SUCCESS('Project synchronization completed'))
            
        except Exception as e:
            self.stdout.write(
                self.style.ERROR(f'Error synchronizing projects: {str(e)}')
            )
            raise
    
    def sync_tasks(self, api, full_sync=False, limit=None):
        """Synchronize tasks from Planfix."""
        self.stdout.write('Synchronizing tasks...')
        
        try:
            # Get task filters based on sync type
            filters = {}
            if not full_sync:
                # Use last sync time as filter
                last_sync = LogEntry.objects.filter(
                    source='sync_planfix_data',
                    level='INFO',
                    message='Planfix data synchronization completed successfully'
                ).order_by('-timestamp').first()
                
                if last_sync:
                    last_sync_time = last_sync.timestamp.isoformat()
                    filters['updatedAfter'] = last_sync_time
            
            # Get all tasks from Planfix (paginated)
            offset = 0
            page_size = min(100, limit or 100)
            total_tasks = 0
            
            # Get task statuses for reference
            task_statuses = api.get_task_statuses()
            status_map = {status['id']: status['name'] for status in task_statuses}
            
            # Get custom fields for reference
            custom_fields = api.get_task_custom_fields()
            custom_field_map = {field['id']: field['name'] for field in custom_fields}
            
            while True:
                # Check if we've reached the limit
                if limit and total_tasks >= limit:
                    break
                
                # Adjust page size for the last page if limit is set
                if limit and (total_tasks + page_size) > limit:
                    page_size = limit - total_tasks
                
                # Get tasks for this page
                tasks_data = api.get_tasks(filters=filters, limit=page_size, offset=offset)
                tasks = tasks_data.get('tasks', [])
                
                if not tasks:
                    break
                
                self.stdout.write(f'Processing {len(tasks)} tasks (offset: {offset})')
                
                # Process each task
                for task_data in tasks:
                    try:
                        with transaction.atomic():
                            planfix_id = str(task_data.get('id'))
                            
                            # Get detailed task data
                            task_details = api.get_task(planfix_id)
                            
                            # Try to find existing task by Planfix ID
                            task = Task.objects.filter(planfix_id=planfix_id).first()
                            
                            # Extract task data
                            title = task_details.get('title', '')
                            description = task_details.get('description', '')
                            status_id = task_details.get('status', {}).get('id')
                            status = status_map.get(status_id, 'Unknown')
                            
                            # Parse created date
                            created_date_str = task_details.get('createDateTime')
                            created_date = timezone.now()
                            if created_date_str:
                                try:
                                    created_date = timezone.datetime.fromisoformat(created_date_str.replace('Z', '+00:00'))
                                except ValueError:
                                    pass
                            
                            # Parse deadline
                            deadline_str = task_details.get('deadline')
                            deadline = None
                            if deadline_str:
                                try:
                                    deadline = timezone.datetime.fromisoformat(deadline_str.replace('Z', '+00:00'))
                                except ValueError:
                                    pass
                            
                            # Get priority
                            priority_map = {1: 'low', 2: 'normal', 3: 'high', 4: 'urgent'}
                            priority_id = task_details.get('priority', 2)
                            priority = priority_map.get(priority_id, 'normal')
                            
                            # Get project if available
                            project = None
                            project_data = task_details.get('project')
                            if project_data:
                                project_id = str(project_data.get('id'))
                                try:
                                    project = Project.objects.get(planfix_id=project_id)
                                except Project.DoesNotExist:
                                    pass
                            
                            # Get parent task if available
                            parent_task = None
                            parent_data = task_details.get('parent')
                            if parent_data:
                                parent_id = str(parent_data.get('id'))
                                try:
                                    parent_task = Task.objects.get(planfix_id=parent_id)
                                except Task.DoesNotExist:
                                    pass
                            
                            # Extract custom fields
                            custom_fields_data = {}
                            for field in task_details.get('customFields', []):
                                field_id = field.get('id')
                                field_name = custom_field_map.get(field_id, f'field_{field_id}')
                                field_value = field.get('value')
                                if field_value:
                                    custom_fields_data[field_name] = field_value
                            
                            if task:
                                # Update existing task
                                task.title = title
                                task.description = description
                                task.status = status
                                task.created_date = created_date
                                task.deadline = deadline
                                task.priority = priority
                                task.project = project
                                task.parent_task = parent_task
                                task.custom_fields = custom_fields_data
                                task.save()
                            else:
                                # Create new task
                                task = Task.objects.create(
                                    planfix_id=planfix_id,
                                    title=title,
                                    description=description,
                                    status=status,
                                    created_date=created_date,
                                    deadline=deadline,
                                    priority=priority,
                                    project=project,
                                    parent_task=parent_task,
                                    custom_fields=custom_fields_data
                                )
                            
                            # Process assignees
                            assignees = []
                            for assignee_data in task_details.get('assignees', []):
                                assignee_id = str(assignee_data.get('id'))
                                try:
                                    user = User.objects.get(planfix_id=assignee_id)
                                    assignees.append(user)
                                except User.DoesNotExist:
                                    pass
                            
                            # Set assignees
                            task.assignees.set(assignees)
                            
                            # Sync comments
                            self.sync_task_comments(api, task)
                            
                            # Sync attachments
                            self.sync_task_attachments(api, task)
                            
                            self.stdout.write(f'Synchronized task: {title}')
                    
                    except Exception as e:
                        self.stdout.write(
                            self.style.WARNING(f'Error processing task {task_data.get("id")}: {str(e)}')
                        )
                
                # Update counters and offset
                total_tasks += len(tasks)
                offset += len(tasks)
                
                # Check if we've reached the limit
                if limit and total_tasks >= limit:
                    break
            
            self.stdout.write(self.style.SUCCESS(f'Task synchronization completed. Processed {total_tasks} tasks.'))
            
        except Exception as e:
            self.stdout.write(
                self.style.ERROR(f'Error synchronizing tasks: {str(e)}')
            )
            raise
    
    def sync_task_comments(self, api, task):
        """Synchronize comments for a task."""
        try:
            # Get comments from Planfix
            comments_data = api.get_task_comments(task.planfix_id)
            
            for comment_data in comments_data:
                planfix_id = str(comment_data.get('id'))
                
                # Try to find existing comment by Planfix ID
                comment = Comment.objects.filter(planfix_id=planfix_id).first()
                
                # Extract comment data
                text = comment_data.get('text', '')
                
                # Parse created date
                created_date_str = comment_data.get('createDateTime')
                created_date = timezone.now()
                if created_date_str:
                    try:
                        created_date = timezone.datetime.fromisoformat(created_date_str.replace('Z', '+00:00'))
                    except ValueError:
                        pass
                
                # Get author if available
                author = None
                author_data = comment_data.get('author')
                if author_data:
                    author_id = str(author_data.get('id'))
                    try:
                        author = User.objects.get(planfix_id=author_id)
                    except User.DoesNotExist:
                        # Create a placeholder user if the author doesn't exist
                        author = User.objects.create(
                            planfix_id=author_id,
                            username=f"planfix_{author_id}",
                            first_name=author_data.get('firstName', ''),
                            last_name=author_data.get('lastName', ''),
                            role='collaborator'
                        )
                
                if not author:
                    # Skip comments without an author
                    continue
                
                if comment:
                    # Update existing comment
                    comment.text = text
                    comment.created_date = created_date
                    comment.author = author
                    comment.save()
                else:
                    # Create new comment
                    comment = Comment.objects.create(
                        planfix_id=planfix_id,
                        task=task,
                        text=text,
                        created_date=created_date,
                        author=author
                    )
                
                # Sync attachments for this comment (if API supports it)
                # Note: This would require additional API functionality
        
        except Exception as e:
            self.stdout.write(
                self.style.WARNING(f'Error synchronizing comments for task {task.planfix_id}: {str(e)}')
            )
    
    def sync_task_attachments(self, api, task):
        """Synchronize attachments for a task."""
        try:
            # Get attachments from Planfix
            attachments_data = api.get_task_attachments(task.planfix_id)
            
            for attachment_data in attachments_data:
                planfix_id = str(attachment_data.get('id'))
                
                # Try to find existing attachment by Planfix ID
                attachment = Attachment.objects.filter(planfix_id=planfix_id).first()
                
                # Extract attachment data
                name = attachment_data.get('name', '')
                file_url = attachment_data.get('downloadUrl', '')
                file_size = attachment_data.get('size', 0)
                file_type = attachment_data.get('mimeType', '')
                
                # Parse upload date
                upload_date_str = attachment_data.get('createDateTime')
                upload_date = timezone.now()
                if upload_date_str:
                    try:
                        upload_date = timezone.datetime.fromisoformat(upload_date_str.replace('Z', '+00:00'))
                    except ValueError:
                        pass
                
                if attachment:
                    # Update existing attachment
                    attachment.name = name
                    attachment.file_url = file_url
                    attachment.file_size = file_size
                    attachment.file_type = file_type
                    attachment.upload_date = upload_date
                    attachment.save()
                else:
                    # Create new attachment
                    attachment = Attachment.objects.create(
                        planfix_id=planfix_id,
                        task=task,
                        name=name,
                        file_url=file_url,
                        file_size=file_size,
                        file_type=file_type,
                        upload_date=upload_date
                    )
                
                # Optional: Download the file locally if needed
                # This could be resource-intensive, so consider if it's necessary
                # self.download_attachment_file(api, attachment)
        
        except Exception as e:
            self.stdout.write(
                self.style.WARNING(f'Error synchronizing attachments for task {task.planfix_id}: {str(e)}')
            )
    
    def download_attachment_file(self, api, attachment):
        """Download the file for an attachment."""
        try:
            # Skip if the file is already downloaded
            if attachment.local_file:
                return
            
            # Download the file
            file_content = api.download_file(attachment.planfix_id)
            
            # Save the file locally
            from django.core.files.base import ContentFile
            attachment.local_file.save(attachment.name, ContentFile(file_content), save=True)
            
        except Exception as e:
            logger.error(f"Error downloading file for attachment {attachment.planfix_id}: {str(e)}")
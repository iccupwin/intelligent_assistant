import json
import logging
from django.shortcuts import render, redirect, get_object_or_404
from django.http import JsonResponse, HttpResponseBadRequest, Http404
from django.views.generic import View, ListView, DetailView
from django.contrib.auth.mixins import LoginRequiredMixin
from django.utils.translation import gettext_lazy as _
from django.utils import timezone
from django.db.models import Q, Count, F
from django.core.paginator import Paginator

from core.models import Task, Project, Comment, User, Attachment, VectorDBMetadata
from core.planfix_api import PlanfixAPI, PlanfixAPIError

logger = logging.getLogger(__name__)


class DashboardView(LoginRequiredMixin, View):
    """View for the dashboard with statistics and summary data."""
    
    template_name = 'dashboard/index.html'
    
    def get(self, request, *args, **kwargs):
        # Get statistics
        try:
            # Task statistics
            task_count = Task.objects.count()
            
            # Status distribution
            status_distribution = Task.objects.values('status').annotate(
                count=Count('id')
            ).order_by('-count')
            
            # Calculate overdue tasks
            overdue_tasks = Task.objects.filter(
                deadline__lt=timezone.now()
            ).exclude(
                status__in=['completed', 'closed', 'done']
            ).count()
            
            # Priority distribution
            priority_distribution = Task.objects.values('priority').annotate(
                count=Count('id')
            ).order_by('priority')
            
            # Project statistics
            project_count = Project.objects.count()
            
            # Project status distribution
            project_status_distribution = Project.objects.values('status').annotate(
                count=Count('id')
            ).order_by('-count')
            
            # User statistics
            user_count = User.objects.count()
            
            # Active users (users active in the last 7 days)
            active_users = User.objects.filter(
                last_active__gte=timezone.now() - timezone.timedelta(days=7)
            ).count()
            
            # Vector database statistics
            try:
                vector_db_stats = VectorDBMetadata.objects.first()
            except:
                vector_db_stats = None
            
            # Prepare context
            context = {
                'task_stats': {
                    'total': task_count,
                    'overdue': overdue_tasks,
                    'status_distribution': list(status_distribution),
                    'priority_distribution': list(priority_distribution)
                },
                'project_stats': {
                    'total': project_count,
                    'status_distribution': list(project_status_distribution),
                },
                'user_stats': {
                    'total': user_count,
                    'active': active_users
                },
                'vector_db_stats': vector_db_stats
            }
            
            return render(request, self.template_name, context)
            
        except Exception as e:
            logger.error(f"Error getting dashboard data: {str(e)}")
            context = {
                'error': _('Error loading dashboard data. Please try again later.')
            }
            return render(request, self.template_name, context)


class TaskListView(LoginRequiredMixin, ListView):
    """View for listing tasks."""
    
    template_name = 'data/task_list.html'
    context_object_name = 'tasks'
    paginate_by = 20
    
    def get_queryset(self):
        queryset = Task.objects.all()
        
        # Apply filters
        status = self.request.GET.get('status')
        if status:
            queryset = queryset.filter(status=status)
        
        priority = self.request.GET.get('priority')
        if priority:
            queryset = queryset.filter(priority=priority)
        
        project_id = self.request.GET.get('project')
        if project_id:
            queryset = queryset.filter(project_id=project_id)
        
        assignee_id = self.request.GET.get('assignee')
        if assignee_id:
            queryset = queryset.filter(assignees__id=assignee_id)
        
        search_query = self.request.GET.get('q')
        if search_query:
            queryset = queryset.filter(
                Q(title__icontains=search_query) | 
                Q(description__icontains=search_query)
            )
        
        # Apply role-based filtering
        user = self.request.user
        if user.role == 'collaborator':
            # Collaborators can only see tasks they are assigned to
            queryset = queryset.filter(assignees=user)
        elif user.role == 'manager':
            # Managers can see all tasks in their projects
            managed_projects = Project.objects.filter(responsible_persons=user)
            queryset = queryset.filter(
                Q(assignees=user) | Q(project__in=managed_projects)
            )
        # Administrators can see all tasks
        
        # Apply sorting
        sort_by = self.request.GET.get('sort', '-created_date')
        queryset = queryset.order_by(sort_by)
        
        return queryset
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        
        # Add filters for template
        context['statuses'] = Task.objects.values_list('status', flat=True).distinct()
        context['priorities'] = [choice[0] for choice in Task.PRIORITY_CHOICES]
        context['projects'] = Project.objects.all()
        context['assignees'] = User.objects.all()
        
        # Add current filters
        context['current_filters'] = {
            'status': self.request.GET.get('status', ''),
            'priority': self.request.GET.get('priority', ''),
            'project': self.request.GET.get('project', ''),
            'assignee': self.request.GET.get('assignee', ''),
            'q': self.request.GET.get('q', ''),
            'sort': self.request.GET.get('sort', '-created_date')
        }
        
        return context


class TaskDetailView(LoginRequiredMixin, DetailView):
    """View for task details."""
    
    template_name = 'data/task_detail.html'
    model = Task
    context_object_name = 'task'
    
    def get_object(self, queryset=None):
        # Get task by ID
        task_id = self.kwargs.get('task_id')
        task = get_object_or_404(Task, id=task_id)
        
        # Check permissions
        user = self.request.user
        if user.role == 'collaborator' and user not in task.assignees.all():
            raise Http404("Task not found")
        
        return task
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        
        # Add comments and attachments
        context['comments'] = self.object.comments.all().order_by('created_date')
        context['attachments'] = self.object.attachments.all()
        
        # Add related tasks (subtasks) if any
        context['subtasks'] = self.object.subtasks.all()
        
        return context


class ProjectListView(LoginRequiredMixin, ListView):
    """View for listing projects."""
    
    template_name = 'data/project_list.html'
    context_object_name = 'projects'
    paginate_by = 20
    
    def get_queryset(self):
        queryset = Project.objects.all()
        
        # Apply filters
        status = self.request.GET.get('status')
        if status:
            queryset = queryset.filter(status=status)
        
        responsible_id = self.request.GET.get('responsible')
        if responsible_id:
            queryset = queryset.filter(responsible_persons__id=responsible_id)
        
        search_query = self.request.GET.get('q')
        if search_query:
            queryset = queryset.filter(
                Q(name__icontains=search_query) | 
                Q(description__icontains=search_query)
            )
        
        # Apply role-based filtering
        user = self.request.user
        if user.role == 'collaborator':
            # Collaborators can only see projects they are responsible for
            queryset = queryset.filter(responsible_persons=user)
        # Managers and Administrators can see all projects
        
        # Apply sorting
        sort_by = self.request.GET.get('sort', '-created_date')
        queryset = queryset.order_by(sort_by)
        
        return queryset
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        
        # Add filters for template
        context['statuses'] = Project.objects.values_list('status', flat=True).distinct()
        context['responsibles'] = User.objects.all()
        
        # Add current filters
        context['current_filters'] = {
            'status': self.request.GET.get('status', ''),
            'responsible': self.request.GET.get('responsible', ''),
            'q': self.request.GET.get('q', ''),
            'sort': self.request.GET.get('sort', '-created_date')
        }
        
        return context


class ProjectDetailView(LoginRequiredMixin, DetailView):
    """View for project details."""
    
    template_name = 'data/project_detail.html'
    model = Project
    context_object_name = 'project'
    
    def get_object(self, queryset=None):
        # Get project by ID
        project_id = self.kwargs.get('project_id')
        project = get_object_or_404(Project, id=project_id)
        
        # Check permissions
        user = self.request.user
        if user.role == 'collaborator' and user not in project.responsible_persons.all():
            raise Http404("Project not found")
        
        return project
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        
        # Add project tasks
        context['tasks'] = self.object.tasks.all().order_by('-created_date')
        
        # Add attachments
        context['attachments'] = self.object.attachments.all()
        
        # Add responsible persons
        context['responsible_persons'] = self.object.responsible_persons.all()
        
        return context


class FileDownloadView(LoginRequiredMixin, View):
    """View for downloading files."""
    
    def get(self, request, *args, **kwargs):
        file_id = kwargs.get('file_id')
        
        try:
            # Get attachment
            attachment = get_object_or_404(Attachment, id=file_id)
            
            # Check permissions
            user = request.user
            has_permission = False
            
            # Administrators can access any file
            if user.role == 'administrator':
                has_permission = True
            else:
                # Check task attachment permissions
                if attachment.task:
                    if user.role == 'manager':
                        # Managers can access files in their projects
                        if attachment.task.project and user in attachment.task.project.responsible_persons.all():
                            has_permission = True
                    
                    # Anyone assigned to the task can access its files
                    if user in attachment.task.assignees.all():
                        has_permission = True
                
                # Check project attachment permissions
                if attachment.project:
                    if user.role == 'manager' or user in attachment.project.responsible_persons.all():
                        has_permission = True
                
                # Check comment attachment permissions
                if attachment.comment:
                    # Same rules as for the task the comment belongs to
                    task = attachment.comment.task
                    if user.role == 'manager' and task.project and user in task.project.responsible_persons.all():
                        has_permission = True
                    if user in task.assignees.all():
                        has_permission = True
            
            if not has_permission:
                return JsonResponse({
                    'success': False,
                    'error': 'Permission denied'
                }, status=403)
            
            # Check if file is already downloaded
            if attachment.local_file:
                # Return local file
                from django.http import FileResponse
                return FileResponse(attachment.local_file, as_attachment=True, filename=attachment.name)
            else:
                # Download file from Planfix
                try:
                    api = PlanfixAPI()
                    file_content = api.download_file(attachment.planfix_id)
                    
                    # Save file to disk
                    from django.core.files.base import ContentFile
                    attachment.local_file.save(attachment.name, ContentFile(file_content), save=True)
                    
                    # Return the file
                    from django.http import HttpResponse
                    response = HttpResponse(file_content, content_type=attachment.file_type)
                    response['Content-Disposition'] = f'attachment; filename="{attachment.name}"'
                    return response
                    
                except PlanfixAPIError as e:
                    logger.error(f"Error downloading file from Planfix: {str(e)}")
                    return JsonResponse({
                        'success': False,
                        'error': f"Error downloading file: {str(e)}"
                    }, status=500)
                
        except Exception as e:
            logger.error(f"Error in FileDownloadView: {str(e)}")
            return JsonResponse({
                'success': False,
                'error': 'An error occurred while downloading the file'
            }, status=500)


class UserListView(LoginRequiredMixin, ListView):
    """View for listing users."""
    
    template_name = 'data/user_list.html'
    context_object_name = 'users'
    paginate_by = 20
    
    def get_queryset(self):
        # Only administrators can see all users
        if self.request.user.role != 'administrator':
            return User.objects.none()
        
        queryset = User.objects.all()
        
        # Apply filters
        role = self.request.GET.get('role')
        if role:
            queryset = queryset.filter(role=role)
        
        search_query = self.request.GET.get('q')
        if search_query:
            queryset = queryset.filter(
                Q(username__icontains=search_query) | 
                Q(first_name__icontains=search_query) | 
                Q(last_name__icontains=search_query) | 
                Q(email__icontains=search_query)
            )
        
        # Apply sorting
        sort_by = self.request.GET.get('sort', 'username')
        queryset = queryset.order_by(sort_by)
        
        return queryset
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        
        # Add filters for template
        context['roles'] = [choice[0] for choice in User.ROLE_CHOICES]
        
        # Add current filters
        context['current_filters'] = {
            'role': self.request.GET.get('role', ''),
            'q': self.request.GET.get('q', ''),
            'sort': self.request.GET.get('sort', 'username')
        }
        
        return context


class APIDataView(LoginRequiredMixin, View):
    """View for accessing Planfix data via API."""
    
    def get(self, request, *args, **kwargs):
        # Ensure only managers and administrators can access API data
        if request.user.role not in ['administrator', 'manager']:
            return JsonResponse({
                'success': False,
                'error': 'Permission denied'
            }, status=403)
        
        data_type = kwargs.get('data_type')
        item_id = kwargs.get('item_id')
        
        try:
            api = PlanfixAPI()
            
            if data_type == 'task':
                if item_id:
                    data = api.get_task(item_id)
                else:
                    # Get tasks with optional filters
                    filters = {}
                    for key, value in request.GET.items():
                        if key not in ['page', 'limit']:
                            filters[key] = value
                    
                    limit = int(request.GET.get('limit', 20))
                    page = int(request.GET.get('page', 1))
                    offset = (page - 1) * limit
                    
                    data = api.get_tasks(filters=filters, limit=limit, offset=offset)
                
            elif data_type == 'project':
                if item_id:
                    data = api.get_project(item_id)
                else:
                    # Get projects with optional filters
                    filters = {}
                    for key, value in request.GET.items():
                        if key not in ['page', 'limit']:
                            filters[key] = value
                    
                    limit = int(request.GET.get('limit', 20))
                    page = int(request.GET.get('page', 1))
                    offset = (page - 1) * limit
                    
                    data = api.get_projects(filters=filters, limit=limit, offset=offset)
                
            elif data_type == 'employee':
                if item_id:
                    data = api.get_employee(item_id)
                else:
                    # Get employees with optional filters
                    filters = {}
                    for key, value in request.GET.items():
                        if key not in ['page', 'limit']:
                            filters[key] = value
                    
                    limit = int(request.GET.get('limit', 20))
                    page = int(request.GET.get('page', 1))
                    offset = (page - 1) * limit
                    
                    data = api.get_employees(filters=filters, limit=limit, offset=offset)
                
            elif data_type == 'task_comments':
                if item_id:
                    data = api.get_task_comments(item_id)
                else:
                    return JsonResponse({
                        'success': False,
                        'error': 'Task ID is required for comments'
                    }, status=400)
                
            elif data_type == 'task_attachments':
                if item_id:
                    data = api.get_task_attachments(item_id)
                else:
                    return JsonResponse({
                        'success': False,
                        'error': 'Task ID is required for attachments'
                    }, status=400)
                
            elif data_type == 'task_statuses':
                data = api.get_task_statuses()
                
            elif data_type == 'project_statuses':
                data = api.get_project_statuses()
                
            else:
                return JsonResponse({
                    'success': False,
                    'error': f'Unknown data type: {data_type}'
                }, status=400)
            
            return JsonResponse({
                'success': True,
                'data': data
            })
            
        except PlanfixAPIError as e:
            logger.error(f"Error getting Planfix API data: {str(e)}")
            return JsonResponse({
                'success': False,
                'error': f"Error getting data: {str(e)}"
            }, status=500)
        except Exception as e:
            logger.error(f"Unexpected error in APIDataView: {str(e)}")
            return JsonResponse({
                'success': False,
                'error': 'An unexpected error occurred'
            }, status=500)


class VectorDatabaseStatusView(LoginRequiredMixin, View):
    """View for checking vector database status."""
    
    def get(self, request, *args, **kwargs):
        # Ensure only administrators can access vector database status
        if request.user.role != 'administrator':
            return JsonResponse({
                'success': False,
                'error': 'Permission denied'
            }, status=403)
        
        try:
            # Get vector database metadata
            metadata = VectorDBMetadata.objects.first()
            
            if not metadata:
                return JsonResponse({
                    'success': True,
                    'status': 'not_initialized',
                    'message': 'Vector database not initialized'
                })
            
            # Initialize vectorizer to get detailed stats
            vectorizer = Vectorizer()
            stats = vectorizer.get_vector_database_stats()
            
            # Combine with database metadata
            result = {
                'success': True,
                'status': metadata.index_status,
                'last_indexed': metadata.last_indexed.isoformat() if metadata.last_indexed else None,
                'total_vectors': metadata.total_vectors,
                'tasks_indexed': metadata.tasks_indexed,
                'projects_indexed': metadata.projects_indexed,
                'comments_indexed': metadata.comments_indexed,
                'detailed_stats': stats
            }
            
            return JsonResponse(result)
            
        except Exception as e:
            logger.error(f"Error getting vector database status: {str(e)}")
            return JsonResponse({
                'success': False,
                'error': f"Error getting vector database status: {str(e)}"
            }, status=500)


class TriggerDataSyncView(LoginRequiredMixin, View):
    """View for triggering data synchronization."""
    
    def post(self, request, *args, **kwargs):
        # Ensure only administrators can trigger data sync
        if request.user.role != 'administrator':
            return JsonResponse({
                'success': False,
                'error': 'Permission denied'
            }, status=403)
        
        try:
            # Determine what to sync
            data = json.loads(request.body)
            sync_type = data.get('sync_type', 'all')
            
            # Import management command function
            from django.core.management import call_command
            
            # Prepare command arguments
            command_args = []
            
            if sync_type == 'tasks':
                command_args.append('--tasks-only')
            elif sync_type == 'projects':
                command_args.append('--projects-only')
            elif sync_type == 'employees':
                command_args.append('--users-only')
            elif sync_type == 'full':
                command_args.append('--full')
            
            # Call management command
            from threading import Thread
            
            def run_sync_command():
                try:
                    call_command('sync_planfix_data', *command_args)
                except Exception as e:
                    logger.error(f"Error during async data sync: {str(e)}")
            
            # Start sync in background thread
            sync_thread = Thread(target=run_sync_command)
            sync_thread.daemon = True
            sync_thread.start()
            
            return JsonResponse({
                'success': True,
                'message': f'Data synchronization ({sync_type}) started in background',
                'sync_type': sync_type
            })
            
        except Exception as e:
            logger.error(f"Error triggering data sync: {str(e)}")
            return JsonResponse({
                'success': False,
                'error': f"Error triggering data sync: {str(e)}"
            }, status=500)


class TriggerVectorUpdateView(LoginRequiredMixin, View):
    """View for triggering vector database update."""
    
    def post(self, request, *args, **kwargs):
        # Ensure only administrators can trigger vector update
        if request.user.role != 'administrator':
            return JsonResponse({
                'success': False,
                'error': 'Permission denied'
            }, status=403)
        
        try:
            # Determine update type
            data = json.loads(request.body)
            update_type = data.get('update_type', 'update')
            
            # Import management command function
            from django.core.management import call_command
            
            # Prepare command arguments
            command_args = []
            
            if update_type == 'rebuild':
                command_args.append('--rebuild')
            elif update_type == 'tasks':
                command_args.append('--tasks-only')
            elif update_type == 'projects':
                command_args.append('--projects-only')
            elif update_type == 'comments':
                command_args.append('--comments-only')
            
            # Call management command
            from threading import Thread
            
            def run_update_command():
                try:
                    call_command('update_vector_db', *command_args)
                except Exception as e:
                    logger.error(f"Error during async vector update: {str(e)}")
            
            # Start update in background thread
            update_thread = Thread(target=run_update_command)
            update_thread.daemon = True
            update_thread.start()
            
            return JsonResponse({
                'success': True,
                'message': f'Vector database update ({update_type}) started in background',
                'update_type': update_type
            })
            
        except Exception as e:
            logger.error(f"Error triggering vector update: {str(e)}")
            return JsonResponse({
                'success': False,
                'error': f"Error triggering vector update: {str(e)}"
            }, status=500)
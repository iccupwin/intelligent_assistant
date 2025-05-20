import time
import logging
from django.core.management.base import BaseCommand
from django.conf import settings
from django.utils import timezone

from core.vectorization import Vectorizer, VectorizationError
from core.models import LogEntry, VectorDBMetadata

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = 'Update the vector database with Planfix data'
    
    def add_arguments(self, parser):
        parser.add_argument(
            '--rebuild',
            action='store_true',
            help='Rebuild the vector database from scratch',
        )
        parser.add_argument(
            '--tasks-only',
            action='store_true',
            help='Update only task vectors',
        )
        parser.add_argument(
            '--projects-only',
            action='store_true',
            help='Update only project vectors',
        )
        parser.add_argument(
            '--comments-only',
            action='store_true',
            help='Update only comment vectors',
        )
    
    def handle(self, *args, **options):
        start_time = time.time()
        self.stdout.write(self.style.SUCCESS('Starting vector database update...'))
        
        # Create log entry for start
        LogEntry.objects.create(
            level='INFO',
            source='update_vector_db',
            message='Starting vector database update',
            metadata={
                'options': {k: v for k, v in options.items() if k != '_'}
            }
        )
        
        try:
            # Initialize Vectorizer
            vectorizer = Vectorizer()
            
            # Rebuild or update
            if options['rebuild']:
                self.rebuild_vector_database(vectorizer)
            else:
                # Update specific data types if specified
                tasks_only = options['tasks_only']
                projects_only = options['projects_only']
                comments_only = options['comments_only']
                
                # If no specific type is specified, update all
                update_all = not (tasks_only or projects_only or comments_only)
                
                self.update_vector_database(vectorizer, update_all, tasks_only, projects_only, comments_only)
            
            end_time = time.time()
            duration = round(end_time - start_time, 2)
            
            # Get database stats
            stats = vectorizer.get_vector_database_stats()
            
            # Create log entry for completion
            LogEntry.objects.create(
                level='INFO',
                source='update_vector_db',
                message='Vector database update completed successfully',
                metadata={
                    'duration_seconds': duration,
                    'total_vectors': stats.get('total_vectors', 0),
                    'type_counts': stats.get('type_counts', {})
                }
            )
            
            self.stdout.write(
                self.style.SUCCESS(f'Vector database update completed in {duration} seconds')
            )
            
            # Print stats
            self.stdout.write(f'Total vectors: {stats.get("total_vectors", 0)}')
            for type_name, count in stats.get('type_counts', {}).items():
                self.stdout.write(f'  - {type_name}: {count}')
            
        except Exception as e:
            # Log error
            LogEntry.objects.create(
                level='ERROR',
                source='update_vector_db',
                message=f'Error during vector database update: {str(e)}',
                metadata={
                    'exception_type': str(type(e).__name__)
                }
            )
            
            self.stdout.write(
                self.style.ERROR(f'Error during vector database update: {str(e)}')
            )
    
    def rebuild_vector_database(self, vectorizer):
        """Rebuild the vector database from scratch."""
        from core.models import Task, Project, Comment
        
        self.stdout.write('Rebuilding vector database...')
        
        # Get current counts for logging
        tasks_count = Task.objects.count()
        projects_count = Project.objects.count()
        comments_count = Comment.objects.count()
        
        # Update database status
        VectorDBMetadata.objects.update_or_create(
            defaults={
                'total_vectors': 0,
                'tasks_indexed': 0,
                'projects_indexed': 0,
                'comments_indexed': 0,
                'index_status': 'rebuilding'
            }
        )
        
        try:
            # Create a new index (this will reset the existing one)
            vectorizer._create_new_faiss_index()
            
            # Reset vector IDs in the database
            Task.objects.all().update(vector_id=None)
            Project.objects.all().update(vector_id=None)
            Comment.objects.all().update(vector_id=None)
            
            # Vectorize all data
            stats = vectorizer.vectorize_planfix_data()
            
            # Log results
            self.stdout.write(f'Rebuilt vector database:')
            self.stdout.write(f'  - Tasks: {stats["tasks"]}/{tasks_count}')
            self.stdout.write(f'  - Projects: {stats["projects"]}/{projects_count}')
            self.stdout.write(f'  - Comments: {stats["comments"]}/{comments_count}')
            
            if stats['errors']:
                self.stdout.write(f'  - Errors: {len(stats["errors"])}')
                for error in stats['errors'][:5]:  # Show first 5 errors
                    self.stdout.write(f'    - {error}')
                if len(stats['errors']) > 5:
                    self.stdout.write(f'    - ... and {len(stats["errors"]) - 5} more errors')
            
        except Exception as e:
            self.stdout.write(
                self.style.ERROR(f'Error rebuilding vector database: {str(e)}')
            )
            # Update database status
            VectorDBMetadata.objects.update_or_create(
                defaults={'index_status': 'error'}
            )
            raise
    
    def update_vector_database(self, vectorizer, update_all=True, tasks_only=False, projects_only=False, comments_only=False):
        """Update the vector database with new or changed data."""
        from core.models import Task, Project, Comment
        
        self.stdout.write('Updating vector database...')
        
        # Update database status
        VectorDBMetadata.objects.update_or_create(
            defaults={'index_status': 'updating'}
        )
        
        try:
            stats = {
                'tasks': 0,
                'projects': 0,
                'comments': 0,
                'errors': []
            }
            
            # Update tasks
            if update_all or tasks_only:
                self.stdout.write('Updating task vectors...')
                unvectorized_tasks = Task.objects.filter(vector_id__isnull=True)
                self.stdout.write(f'Found {unvectorized_tasks.count()} unvectorized tasks')
                
                for task in unvectorized_tasks:
                    try:
                        # Prepare text for vectorization
                        task_text = f"""
                        Task: {task.title}
                        Description: {task.description or ''}
                        Status: {task.status}
                        Priority: {task.priority}
                        Project: {task.project.name if task.project else 'None'}
                        """
                        
                        # Add custom fields if any
                        if task.custom_fields:
                            custom_fields_str = "\n".join([f"{k}: {v}" for k, v in task.custom_fields.items()])
                            task_text += f"\nCustom Fields:\n{custom_fields_str}"
                        
                        # Prepare metadata
                        metadata = {
                            'type': 'task',
                            'planfix_id': task.planfix_id,
                            'database_id': task.id,
                            'title': task.title,
                            'status': task.status,
                            'priority': task.priority,
                            'deadline': task.deadline.isoformat() if task.deadline else None,
                            'project_id': task.project.id if task.project else None,
                            'project_name': task.project.name if task.project else None
                        }
                        
                        # Add vector
                        vector_id = vectorizer.add_vector(task_text, metadata)
                        
                        # Update task with vector ID
                        task.vector_id = str(vector_id)
                        task.save(update_fields=['vector_id'])
                        
                        stats['tasks'] += 1
                        
                    except Exception as e:
                        logger.error(f"Error vectorizing task {task.id}: {str(e)}")
                        stats['errors'].append(f"Task {task.id}: {str(e)}")
            
            # Update projects
            if update_all or projects_only:
                self.stdout.write('Updating project vectors...')
                unvectorized_projects = Project.objects.filter(vector_id__isnull=True)
                self.stdout.write(f'Found {unvectorized_projects.count()} unvectorized projects')
                
                for project in unvectorized_projects:
                    try:
                        # Prepare text for vectorization
                        project_text = f"""
                        Project: {project.name}
                        Description: {project.description or ''}
                        Status: {project.status}
                        Created: {project.created_date.strftime('%Y-%m-%d')}
                        """
                        
                        # Add custom fields if any
                        if project.custom_fields:
                            custom_fields_str = "\n".join([f"{k}: {v}" for k, v in project.custom_fields.items()])
                            project_text += f"\nCustom Fields:\n{custom_fields_str}"
                        
                        # Prepare metadata
                        metadata = {
                            'type': 'project',
                            'planfix_id': project.planfix_id,
                            'database_id': project.id,
                            'name': project.name,
                            'status': project.status,
                            'created_date': project.created_date.isoformat()
                        }
                        
                        # Add vector
                        vector_id = vectorizer.add_vector(project_text, metadata)
                        
                        # Update project with vector ID
                        project.vector_id = str(vector_id)
                        project.save(update_fields=['vector_id'])
                        
                        stats['projects'] += 1
                        
                    except Exception as e:
                        logger.error(f"Error vectorizing project {project.id}: {str(e)}")
                        stats['errors'].append(f"Project {project.id}: {str(e)}")
            
            # Update comments
            if update_all or comments_only:
                self.stdout.write('Updating comment vectors...')
                unvectorized_comments = Comment.objects.filter(vector_id__isnull=True)
                self.stdout.write(f'Found {unvectorized_comments.count()} unvectorized comments')
                
                for comment in unvectorized_comments:
                    try:
                        # Prepare text for vectorization
                        comment_text = f"""
                        Comment by {comment.author.username} on task '{comment.task.title}' ({comment.created_date.strftime('%Y-%m-%d')}):
                        {comment.text}
                        """
                        
                        # Prepare metadata
                        metadata = {
                            'type': 'comment',
                            'planfix_id': comment.planfix_id,
                            'database_id': comment.id,
                            'task_id': comment.task.id,
                            'task_title': comment.task.title,
                            'author_id': comment.author.id,
                            'author_name': comment.author.username,
                            'created_date': comment.created_date.isoformat()
                        }
                        
                        # Add vector
                        vector_id = vectorizer.add_vector(comment_text, metadata)
                        
                        # Update comment with vector ID
                        comment.vector_id = str(vector_id)
                        comment.save(update_fields=['vector_id'])
                        
                        stats['comments'] += 1
                        
                    except Exception as e:
                        logger.error(f"Error vectorizing comment {comment.id}: {str(e)}")
                        stats['errors'].append(f"Comment {comment.id}: {str(e)}")
            
            # Save index
            vectorizer._save_faiss_index()
            
            # Update database statistics
            VectorDBMetadata.objects.update_or_create(
                defaults={
                    'total_vectors': vectorizer.index.ntotal,
                    'tasks_indexed': Task.objects.filter(vector_id__isnull=False).count(),
                    'projects_indexed': Project.objects.filter(vector_id__isnull=False).count(),
                    'comments_indexed': Comment.objects.filter(vector_id__isnull=False).count(),
                    'index_status': 'ready'
                }
            )
            
            # Log results
            self.stdout.write(f'Updated vector database:')
            self.stdout.write(f'  - Tasks: {stats["tasks"]}')
            self.stdout.write(f'  - Projects: {stats["projects"]}')
            self.stdout.write(f'  - Comments: {stats["comments"]}')
            
            if stats['errors']:
                self.stdout.write(f'  - Errors: {len(stats["errors"])}')
                for error in stats['errors'][:5]:  # Show first 5 errors
                    self.stdout.write(f'    - {error}')
                if len(stats['errors']) > 5:
                    self.stdout.write(f'    - ... and {len(stats["errors"]) - 5} more errors')
            
        except Exception as e:
            self.stdout.write(
                self.style.ERROR(f'Error updating vector database: {str(e)}')
            )
            # Update database status
            VectorDBMetadata.objects.update_or_create(
                defaults={'index_status': 'error'}
            )
            raise
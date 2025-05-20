from django.db import models
from django.contrib.auth.models import AbstractUser
from django.utils.translation import gettext_lazy as _
from django.utils import timezone
import uuid
import json


class User(AbstractUser):
    """Extended User model for the intelligent assistant."""
    
    ROLE_CHOICES = (
        ('administrator', _('Administrator')),
        ('manager', _('Manager')),
        ('collaborator', _('Collaborator')),
        ('guest', _('Guest')),
    )
    
    planfix_id = models.CharField(max_length=50, blank=True, null=True)
    role = models.CharField(max_length=20, choices=ROLE_CHOICES, default='collaborator')
    profile_image = models.ImageField(upload_to='profile_images/', blank=True, null=True)
    language_preference = models.CharField(max_length=10, choices=[('en', _('English')), ('ru', _('Russian'))], default='en')
    last_active = models.DateTimeField(null=True, blank=True)
    
    def __str__(self):
        return self.username
    
    def save_last_active(self):
        self.last_active = timezone.now()
        self.save(update_fields=['last_active'])
    
    @property
    def is_administrator(self):
        return self.role == 'administrator'
    
    @property
    def is_manager(self):
        return self.role in ['administrator', 'manager']


class Project(models.Model):
    """Model representing a project from Planfix."""
    
    planfix_id = models.CharField(max_length=50, unique=True)
    name = models.CharField(max_length=255)
    description = models.TextField(blank=True, null=True)
    status = models.CharField(max_length=50)
    created_date = models.DateTimeField()
    last_updated = models.DateTimeField(auto_now=True)
    responsible_persons = models.ManyToManyField(User, related_name='responsible_projects')
    vector_id = models.CharField(max_length=100, blank=True, null=True)
    custom_fields = models.JSONField(default=dict, blank=True)
    
    def __str__(self):
        return self.name
    
    class Meta:
        ordering = ['-created_date']
        indexes = [
            models.Index(fields=['planfix_id']),
            models.Index(fields=['status']),
            models.Index(fields=['created_date']),
        ]


class Task(models.Model):
    """Model representing a task from Planfix."""
    
    PRIORITY_CHOICES = (
        ('low', _('Low')),
        ('normal', _('Normal')),
        ('high', _('High')),
        ('urgent', _('Urgent')),
    )
    
    planfix_id = models.CharField(max_length=50, unique=True)
    title = models.CharField(max_length=255)
    description = models.TextField(blank=True, null=True)
    status = models.CharField(max_length=50)
    created_date = models.DateTimeField()
    deadline = models.DateTimeField(null=True, blank=True)
    priority = models.CharField(max_length=10, choices=PRIORITY_CHOICES, default='normal')
    project = models.ForeignKey('Project', on_delete=models.CASCADE, related_name='tasks', null=True, blank=True)
    assignees = models.ManyToManyField(User, related_name='assigned_tasks')
    parent_task = models.ForeignKey('self', on_delete=models.CASCADE, related_name='subtasks', null=True, blank=True)
    last_updated = models.DateTimeField(auto_now=True)
    vector_id = models.CharField(max_length=100, blank=True, null=True)
    custom_fields = models.JSONField(default=dict, blank=True)
    
    def __str__(self):
        return self.title
    
    @property
    def is_overdue(self):
        if self.deadline:
            return self.deadline < timezone.now()
        return False
    
    class Meta:
        ordering = ['-created_date']
        indexes = [
            models.Index(fields=['planfix_id']),
            models.Index(fields=['status']),
            models.Index(fields=['deadline']),
            models.Index(fields=['priority']),
        ]


class Comment(models.Model):
    """Model representing a comment on a task in Planfix."""
    
    planfix_id = models.CharField(max_length=50, unique=True)
    task = models.ForeignKey(Task, on_delete=models.CASCADE, related_name='comments')
    author = models.ForeignKey(User, on_delete=models.CASCADE, related_name='comments')
    text = models.TextField()
    created_date = models.DateTimeField()
    vector_id = models.CharField(max_length=100, blank=True, null=True)
    
    def __str__(self):
        return f'Comment by {self.author} on {self.task}'
    
    class Meta:
        ordering = ['created_date']
        indexes = [
            models.Index(fields=['planfix_id']),
            models.Index(fields=['created_date']),
        ]


class Attachment(models.Model):
    """Model representing file attachments."""
    
    planfix_id = models.CharField(max_length=50, unique=True)
    task = models.ForeignKey(Task, on_delete=models.CASCADE, related_name='attachments', null=True, blank=True)
    comment = models.ForeignKey(Comment, on_delete=models.CASCADE, related_name='attachments', null=True, blank=True)
    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name='attachments', null=True, blank=True)
    name = models.CharField(max_length=255)
    file_url = models.URLField()
    file_size = models.BigIntegerField(default=0)
    upload_date = models.DateTimeField()
    file_type = models.CharField(max_length=50)
    local_file = models.FileField(upload_to='attachments/', blank=True, null=True)
    
    def __str__(self):
        return self.name


class ChatSession(models.Model):
    """Model for storing chat sessions."""
    
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='chat_sessions')
    title = models.CharField(max_length=255, default="New Conversation")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    def __str__(self):
        return f"{self.title} - {self.user.username}"
    
    class Meta:
        ordering = ['-updated_at']


class ChatMessage(models.Model):
    """Model for storing individual chat messages."""
    
    ROLE_CHOICES = (
        ('user', 'User'),
        ('assistant', 'Assistant'),
    )
    
    session = models.ForeignKey(ChatSession, on_delete=models.CASCADE, related_name='messages')
    role = models.CharField(max_length=10, choices=ROLE_CHOICES)
    content = models.TextField()
    timestamp = models.DateTimeField(auto_now_add=True)
    
    def __str__(self):
        return f"{self.role}: {self.content[:50]}..."
    
    class Meta:
        ordering = ['timestamp']


class AIContext(models.Model):
    """Model for storing context for AI conversations."""
    
    session = models.OneToOneField(ChatSession, on_delete=models.CASCADE, related_name='ai_context')
    context_data = models.JSONField(default=dict)
    related_tasks = models.ManyToManyField(Task, blank=True)
    related_projects = models.ManyToManyField(Project, blank=True)
    last_updated = models.DateTimeField(auto_now=True)
    
    def add_to_context(self, key, value):
        context = self.context_data
        context[key] = value
        self.context_data = context
        self.save()
    
    def get_from_context(self, key, default=None):
        return self.context_data.get(key, default)
    
    def __str__(self):
        return f"Context for session {self.session.id}"


class LogEntry(models.Model):
    """Model for logging AI interactions and system events."""
    
    LOG_LEVEL_CHOICES = (
        ('INFO', 'Information'),
        ('WARNING', 'Warning'),
        ('ERROR', 'Error'),
        ('DEBUG', 'Debug'),
    )
    
    user = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='log_entries')
    timestamp = models.DateTimeField(auto_now_add=True)
    level = models.CharField(max_length=10, choices=LOG_LEVEL_CHOICES, default='INFO')
    message = models.TextField()
    source = models.CharField(max_length=100, default='system')
    metadata = models.JSONField(default=dict, blank=True)
    
    def __str__(self):
        return f"{self.timestamp} - {self.level}: {self.message[:50]}..."
    
    class Meta:
        ordering = ['-timestamp']
        indexes = [
            models.Index(fields=['level']),
            models.Index(fields=['timestamp']),
            models.Index(fields=['source']),
        ]


class VectorDBMetadata(models.Model):
    """Model for tracking vector database status and updates."""
    
    last_indexed = models.DateTimeField(auto_now=True)
    total_vectors = models.IntegerField(default=0)
    tasks_indexed = models.IntegerField(default=0)
    projects_indexed = models.IntegerField(default=0)
    comments_indexed = models.IntegerField(default=0)
    index_status = models.CharField(max_length=20, default='initialized')
    
    def __str__(self):
        return f"Vector DB Status: {self.index_status} (Last updated: {self.last_indexed})"
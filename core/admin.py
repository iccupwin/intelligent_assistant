from django.contrib import admin
from .models import User, Task, Project, Comment, Attachment, ChatSession, ChatMessage, AIContext, LogEntry, VectorDBMetadata

# Register your models here.
admin.site.register(User)
admin.site.register(Task)
admin.site.register(Project)
admin.site.register(Comment)
admin.site.register(Attachment)
admin.site.register(ChatSession)
admin.site.register(ChatMessage)
admin.site.register(AIContext)
admin.site.register(LogEntry)
admin.site.register(VectorDBMetadata)
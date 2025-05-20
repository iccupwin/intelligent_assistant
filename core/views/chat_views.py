import json
import logging
import uuid
from django.shortcuts import render, redirect, get_object_or_404
from django.urls import reverse
from django.http import JsonResponse, HttpResponseBadRequest, Http404
from django.views.generic import View, TemplateView, ListView, DetailView
from django.contrib.auth.mixins import LoginRequiredMixin
from django.utils.translation import gettext_lazy as _
from django.views.decorators.csrf import csrf_exempt
from django.utils.decorators import method_decorator
from django.utils import timezone
from django.db.models import Q

from core.models import ChatSession, ChatMessage, AIContext, LogEntry, Task, Project, Comment
from core.claude_ai import ClaudeAI, ClaudeAIError
from core.vectorization import Vectorizer, VectorizationError
from core.planfix_api import PlanfixAPI, PlanfixAPIError

logger = logging.getLogger(__name__)


class ChatHomeView(LoginRequiredMixin, ListView):
    """Home view showing chat history."""
    
    template_name = 'chat/index.html'
    context_object_name = 'chat_sessions'
    
    def get_queryset(self):
        # Get chat sessions for the current user, ordered by most recent first
        return ChatSession.objects.filter(user=self.request.user).order_by('-updated_at')
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['new_session_id'] = str(uuid.uuid4())
        
        # Get active session if there is one
        active_session_id = self.request.GET.get('session_id')
        if active_session_id:
            try:
                active_session = ChatSession.objects.get(id=active_session_id, user=self.request.user)
                context['active_session'] = active_session
                context['messages'] = active_session.messages.all().order_by('timestamp')
            except ChatSession.DoesNotExist:
                pass
                
        return context


class ChatSessionView(LoginRequiredMixin, DetailView):
    """View for a specific chat session."""
    
    template_name = 'chat/session.html'
    model = ChatSession
    context_object_name = 'session'
    
    def get_object(self, queryset=None):
        # Get chat session by ID, ensuring it belongs to the current user
        session_id = self.kwargs.get('session_id')
        return get_object_or_404(ChatSession, id=session_id, user=self.request.user)
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['messages'] = self.object.messages.all().order_by('timestamp')
        context['chat_sessions'] = ChatSession.objects.filter(user=self.request.user).order_by('-updated_at')
        context['new_session_id'] = str(uuid.uuid4())
        return context


class CreateChatSessionView(LoginRequiredMixin, View):
    """View to create a new chat session."""
    
    def get(self, request, *args, **kwargs):
        # Generate a new session ID
        session_id = kwargs.get('session_id', str(uuid.uuid4()))
        
        # Create a new Claude AI client
        claude_ai = ClaudeAI()
        
        try:
            # Create a new chat session
            session_id = claude_ai.create_chat_session(str(request.user.id))
            
            # Redirect to the chat session
            return redirect(reverse('chat_session', kwargs={'session_id': session_id}))
            
        except Exception as e:
            logger.error(f"Error creating chat session: {str(e)}")
            return redirect(reverse('chat_home'))


class DeleteChatSessionView(LoginRequiredMixin, View):
    """View to delete a chat session."""
    
    def post(self, request, *args, **kwargs):
        session_id = kwargs.get('session_id')
        
        try:
            # Get session and verify ownership
            session = get_object_or_404(ChatSession, id=session_id, user=request.user)
            
            # Delete session
            session.delete()
            
            # Log deletion
            LogEntry.objects.create(
                user=request.user,
                level='INFO',
                source='chat',
                message=f'Chat session {session_id} deleted',
                metadata={
                    'session_title': session.title
                }
            )
            
            return JsonResponse({'success': True})
            
        except Exception as e:
            logger.error(f"Error deleting chat session {session_id}: {str(e)}")
            return JsonResponse({'success': False, 'error': str(e)}, status=400)


@method_decorator(csrf_exempt, name='dispatch')
class ChatMessageView(LoginRequiredMixin, View):
    """View to handle chat messages."""
    
    def post(self, request, *args, **kwargs):
        try:
            # Parse request data
            try:
                data = json.loads(request.body)
                session_id = data.get('session_id')
                message = data.get('message')
                
                if not session_id or not message:
                    return JsonResponse({
                        'success': False,
                        'error': 'Missing session_id or message'
                    }, status=400)
                
            except json.JSONDecodeError:
                return JsonResponse({
                    'success': False,
                    'error': 'Invalid JSON data'
                }, status=400)
            
            # Verify session ownership
            try:
                session = ChatSession.objects.get(id=session_id, user=request.user)
            except ChatSession.DoesNotExist:
                return JsonResponse({
                    'success': False,
                    'error': 'Chat session not found'
                }, status=404)
            
            # Process message with Claude AI
            claude_ai = ClaudeAI()
            
            # First, update user's last active timestamp
            request.user.save_last_active()
            
            # Process the message
            try:
                # If this is the first message in the session, rename it
                if session.messages.count() == 0:
                    # Process the message
                    assistant_response = claude_ai.process_user_message(session_id, message)
                    
                    # Rename the session
                    new_title = claude_ai.rename_chat_session(session_id)
                    
                    # Return response with new title
                    return JsonResponse({
                        'success': True,
                        'response': assistant_response,
                        'title': new_title
                    })
                else:
                    # Process the message
                    assistant_response = claude_ai.process_user_message(session_id, message)
                    
                    # Return response
                    return JsonResponse({
                        'success': True,
                        'response': assistant_response
                    })
                
            except ClaudeAIError as e:
                logger.error(f"Error processing message with Claude AI: {str(e)}")
                return JsonResponse({
                    'success': False,
                    'error': f"Error processing message: {str(e)}"
                }, status=500)
                
        except Exception as e:
            logger.error(f"Unexpected error in ChatMessageView: {str(e)}")
            return JsonResponse({
                'success': False,
                'error': 'An unexpected error occurred'
            }, status=500)


class ChatHistoryView(LoginRequiredMixin, ListView):
    """View showing chat history."""
    
    template_name = 'chat/history.html'
    context_object_name = 'chat_sessions'
    paginate_by = 10
    
    def get_queryset(self):
        # Get chat sessions for the current user, ordered by most recent first
        return ChatSession.objects.filter(user=self.request.user).order_by('-updated_at')


class SearchChatView(LoginRequiredMixin, View):
    """View to search chat history."""
    
    def get(self, request, *args, **kwargs):
        query = request.GET.get('q', '')
        
        if not query:
            return JsonResponse({
                'success': False,
                'error': 'Missing search query'
            }, status=400)
        
        try:
            # Search for chat messages containing the query
            messages = ChatMessage.objects.filter(
                session__user=request.user,
                content__icontains=query
            ).select_related('session').order_by('-timestamp')[:20]
            
            # Format results
            results = []
            for msg in messages:
                results.append({
                    'message_id': str(msg.id),
                    'session_id': str(msg.session.id),
                    'session_title': msg.session.title,
                    'role': msg.role,
                    'content': msg.content[:200] + ('...' if len(msg.content) > 200 else ''),
                    'timestamp': msg.timestamp.isoformat(),
                    'url': reverse('chat_session', kwargs={'session_id': msg.session.id})
                })
            
            return JsonResponse({
                'success': True,
                'results': results,
                'count': len(results)
            })
            
        except Exception as e:
            logger.error(f"Error searching chat history: {str(e)}")
            return JsonResponse({
                'success': False,
                'error': f"Error searching chat history: {str(e)}"
            }, status=500)


class SemanticSearchView(LoginRequiredMixin, View):
    """View to perform semantic search on Planfix data."""
    
    def get(self, request, *args, **kwargs):
        query = request.GET.get('q', '')
        filter_type = request.GET.get('type', None)
        limit = int(request.GET.get('limit', 5))
        
        if not query:
            return JsonResponse({
                'success': False,
                'error': 'Missing search query'
            }, status=400)
        
        try:
            # Initialize vectorizer
            vectorizer = Vectorizer()
            
            # Perform semantic search
            results = vectorizer.semantic_search(query, filter_type, limit)
            
            # Format and return results
            formatted_results = []
            for result in results:
                metadata = result['metadata']
                result_type = metadata.get('type', 'unknown')
                
                item = {
                    'id': result['id'],
                    'type': result_type,
                    'text': result['text'],
                    'similarity': result['similarity'],
                    'metadata': metadata
                }
                
                # Add type-specific data
                if result_type == 'task':
                    item['title'] = metadata.get('title', 'Untitled Task')
                    item['status'] = metadata.get('status', 'Unknown')
                    item['priority'] = metadata.get('priority', 'normal')
                elif result_type == 'project':
                    item['name'] = metadata.get('name', 'Untitled Project')
                    item['status'] = metadata.get('status', 'Unknown')
                elif result_type == 'comment':
                    item['task_title'] = metadata.get('task_title', 'Unknown Task')
                    item['author_name'] = metadata.get('author_name', 'Unknown User')
                
                formatted_results.append(item)
            
            return JsonResponse({
                'success': True,
                'results': formatted_results,
                'count': len(formatted_results)
            })
            
        except Exception as e:
            logger.error(f"Error performing semantic search: {str(e)}")
            return JsonResponse({
                'success': False,
                'error': f"Error performing semantic search: {str(e)}"
            }, status=500)


class ProcessNaturalLanguageQueryView(LoginRequiredMixin, View):
    """View to process natural language queries for Planfix data."""
    
    def post(self, request, *args, **kwargs):
        try:
            # Parse request data
            try:
                data = json.loads(request.body)
                session_id = data.get('session_id')
                query = data.get('query')
                
                if not session_id or not query:
                    return JsonResponse({
                        'success': False,
                        'error': 'Missing session_id or query'
                    }, status=400)
                
            except json.JSONDecodeError:
                return JsonResponse({
                    'success': False,
                    'error': 'Invalid JSON data'
                }, status=400)
            
            # Verify session ownership
            try:
                session = ChatSession.objects.get(id=session_id, user=request.user)
            except ChatSession.DoesNotExist:
                return JsonResponse({
                    'success': False,
                    'error': 'Chat session not found'
                }, status=404)
            
            # Process query with Claude AI
            claude_ai = ClaudeAI()
            
            try:
                # Parse the natural language query
                parsed_query = claude_ai.parse_natural_language_query(session_id, query)
                
                # Fetch data based on the parsed query
                planfix_api = PlanfixAPI()
                
                # Determine which API method to call based on the intent
                intent = parsed_query.get('intent', 'unknown')
                filters = parsed_query.get('filters', {})
                
                data = None
                
                if intent == 'tasks':
                    data = planfix_api.get_tasks(filters=filters)
                elif intent == 'projects':
                    data = planfix_api.get_projects(filters=filters)
                elif intent == 'employees':
                    data = planfix_api.get_employees(filters=filters)
                elif intent == 'task_comments':
                    task_id = filters.get('task_id')
                    if task_id:
                        data = planfix_api.get_task_comments(task_id)
                    else:
                        return JsonResponse({
                            'success': False,
                            'error': 'Missing task_id for comments'
                        }, status=400)
                elif intent == 'task_statuses':
                    data = planfix_api.get_task_statuses()
                elif intent == 'project_statuses':
                    data = planfix_api.get_project_statuses()
                else:
                    return JsonResponse({
                        'success': False,
                        'error': f'Unknown intent: {intent}'
                    }, status=400)
                
                # Analyze the data using Claude AI
                analysis = claude_ai.analyze_planfix_data(session_id, query, data)
                
                # Add user query and AI response to chat history
                claude_ai.add_message(session_id, 'user', query)
                claude_ai.add_message(session_id, 'assistant', analysis)
                
                return JsonResponse({
                    'success': True,
                    'response': analysis,
                    'parsed_query': parsed_query,
                    'data_summary': {
                        'intent': intent,
                        'count': len(data) if isinstance(data, list) else 1
                    }
                })
                
            except (ClaudeAIError, PlanfixAPIError) as e:
                logger.error(f"Error processing natural language query: {str(e)}")
                return JsonResponse({
                    'success': False,
                    'error': f"Error processing query: {str(e)}"
                }, status=500)
                
        except Exception as e:
            logger.error(f"Unexpected error in ProcessNaturalLanguageQueryView: {str(e)}")
            return JsonResponse({
                'success': False,
                'error': 'An unexpected error occurred'
            }, status=500)
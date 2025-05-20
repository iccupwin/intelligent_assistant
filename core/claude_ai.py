import os
import json
import logging
from typing import Dict, List, Optional, Any, Tuple
from anthropic import Anthropic
from datetime import datetime

from django.conf import settings
from django.utils import timezone
from django.core.cache import cache

logger = logging.getLogger(__name__)


class ClaudeAIError(Exception):
    """Custom exception for Claude AI errors."""
    pass


class ClaudeAI:
    """Class to interact with Claude AI via Anthropic API."""
    
    def __init__(self, api_key=None):
        self.api_key = api_key or getattr(settings, 'ANTHROPIC_API_KEY', os.getenv('ANTHROPIC_API_KEY'))
        self.model = getattr(settings, 'CLAUDE_MODEL', 'claude-3-5-sonnet')
        self.max_tokens = getattr(settings, 'CLAUDE_MAX_TOKENS', 4000)
        
        if not self.api_key:
            raise ValueError("Anthropic API key is required")
        
        self.client = Anthropic(api_key=self.api_key)
        
        # Default system prompt with instructions about Planfix data
        self.base_system_prompt = """
        Вы являетесь интеллектуальным ассистентом, интегрированным с системой управления проектами Planfix. 
        Вы можете помочь пользователям с их задачами, проектами и рабочими процессами.
        
        Вы имеете доступ к следующим данным Planfix:
        - Задачи: заголовок, описание, статусы, сроки, приоритеты, вложения, связи с проектами и сотрудниками
        - Проекты: название, описание, текущий статус, ответственные лица, дата создания
        - Сотрудники: полное имя, должности, контактная информация, активность
        - Комментарии к задачам: автор, дата, текст
        
        Ваши возможности включают:
        - Ответы на вопросы о задачах, проектах и сотрудниках
        - Объяснение статуса задач и предоставление рекомендаций по приоритизации
        - Преобразование естественного языка в фильтры и запросы данных
        - Анализ исторической активности и выполнения задач
        - Предоставление контекстно-зависимых ответов в ходе диалога
        - Генерация шаблонов для ответов, писем и отчетов по проектам
        
        Всегда отвечайте вежливо и профессионально. Если вас спросят об информации, к которой у вас нет доступа, 
        объясните, что вы можете получить доступ только к данным Planfix, как описано выше.
        """
    
    def create_chat_session(self, user_id: str, initial_context: Dict = None) -> str:
        """
        Create a new chat session with Claude AI.
        
        Args:
            user_id: ID of the user
            initial_context: Optional initial context for the conversation
            
        Returns:
            Session ID
        """
        from core.models import ChatSession, AIContext, User
        
        user = User.objects.get(id=user_id)
        
        # Create chat session
        session = ChatSession.objects.create(
            user=user,
            title="Новая беседа"
        )
        
        # Create AI context
        context_data = initial_context or {}
        AIContext.objects.create(
            session=session,
            context_data=context_data
        )
        
        return str(session.id)
    
    def _get_conversation_history(self, session_id: str) -> List[Dict]:
        """
        Get conversation history for a chat session.
        
        Args:
            session_id: ID of the chat session
            
        Returns:
            List of message dictionaries
        """
        from core.models import ChatSession, ChatMessage
        
        try:
            session = ChatSession.objects.get(id=session_id)
            messages = []
            
            for msg in session.messages.all():
                messages.append({
                    "role": msg.role,
                    "content": msg.content
                })
            
            return messages
        except ChatSession.DoesNotExist:
            raise ClaudeAIError(f"Chat session {session_id} not found")
    
    def _get_ai_context(self, session_id: str) -> Dict:
        """
        Get AI context for a chat session.
        
        Args:
            session_id: ID of the chat session
            
        Returns:
            Context data dictionary
        """
        from core.models import ChatSession, AIContext
        
        try:
            session = ChatSession.objects.get(id=session_id)
            context, created = AIContext.objects.get_or_create(session=session)
            return context.context_data
        except ChatSession.DoesNotExist:
            raise ClaudeAIError(f"Chat session {session_id} not found")
    
    def _update_ai_context(self, session_id: str, context_updates: Dict) -> None:
        """
        Update AI context for a chat session.
        
        Args:
            session_id: ID of the chat session
            context_updates: Dictionary with context updates
        """
        from core.models import ChatSession, AIContext
        
        try:
            session = ChatSession.objects.get(id=session_id)
            context, created = AIContext.objects.get_or_create(session=session)
            
            # Update context
            current_context = dict(context.context_data)
            current_context.update(context_updates)
            context.context_data = current_context
            context.save()
        except ChatSession.DoesNotExist:
            raise ClaudeAIError(f"Chat session {session_id} not found")
    
    def _prepare_system_prompt(self, session_id: str) -> str:
        """
        Prepare the system prompt for Claude AI with context.
        
        Args:
            session_id: ID of the chat session
            
        Returns:
            System prompt string
        """
        from core.models import ChatSession, User
        
        try:
            session = ChatSession.objects.get(id=session_id)
            user = session.user
            
            # Get AI context
            ai_context = self._get_ai_context(session_id)
            
            # Build context-specific system prompt
            system_prompt = self.base_system_prompt
            
            # Add user information
            system_prompt += f"\n\nТекущий пользователь: {user.username}"
            
            # Add language preference
            if user.language_preference == 'ru':
                system_prompt += "\nПожалуйста, отвечайте на русском языке."
            else:
                system_prompt += "\nПожалуйста, отвечайте на английском языке."
            
            # Add related tasks/projects if available
            if 'related_tasks' in ai_context:
                tasks_str = '\n'.join([f"- {task}" for task in ai_context.get('related_tasks', [])])
                system_prompt += f"\n\nСвязанные задачи в этой беседе:\n{tasks_str}"
                
            if 'related_projects' in ai_context:
                projects_str = '\n'.join([f"- {project}" for project in ai_context.get('related_projects', [])])
                system_prompt += f"\n\nСвязанные проекты в этой беседе:\n{projects_str}"
            
            # Add any custom context
            for key, value in ai_context.items():
                if key not in ['related_tasks', 'related_projects'] and isinstance(value, str):
                    system_prompt += f"\n\n{key.replace('_', ' ').capitalize()}: {value}"
            
            # Add current date
            system_prompt += f"\n\nТекущая дата: {timezone.now().strftime('%Y-%m-%d')}"
            
            return system_prompt
            
        except ChatSession.DoesNotExist:
            raise ClaudeAIError(f"Chat session {session_id} not found")
        except Exception as e:
            logger.error(f"Error preparing system prompt: {str(e)}")
            return self.base_system_prompt
    
    def add_message(self, session_id: str, role: str, content: str) -> None:
        """
        Add a message to the chat session.
        
        Args:
            session_id: ID of the chat session
            role: Role of the message sender ('user' or 'assistant')
            content: Message content
        """
        from core.models import ChatSession, ChatMessage
        
        try:
            session = ChatSession.objects.get(id=session_id)
            
            # Create chat message
            ChatMessage.objects.create(
                session=session,
                role=role,
                content=content
            )
            
            # Update session timestamp
            session.save()  # This will update the updated_at field
            
        except ChatSession.DoesNotExist:
            raise ClaudeAIError(f"Chat session {session_id} not found")
    
    def process_user_message(self, session_id: str, message: str) -> str:
        """
        Process a user message and get a response from Claude AI.
        
        Args:
            session_id: ID of the chat session
            message: User message content
            
        Returns:
            Claude AI response
        """
        # Add user message to chat history
        self.add_message(session_id, 'user', message)
        
        # Get conversation history
        messages = self._get_conversation_history(session_id)
        
        # Prepare system prompt
        system_prompt = self._prepare_system_prompt(session_id)
        
        # Call Claude AI API
        try:
            response = self.client.messages.create(
                model=self.model,
                max_tokens=self.max_tokens,
                system=system_prompt,
                messages=messages
            )
            
            # Extract the assistant's response
            assistant_response = response.content[0].text
            
            # Add assistant response to chat history
            self.add_message(session_id, 'assistant', assistant_response)
            
            return assistant_response
            
        except Exception as e:
            logger.error(f"Error calling Claude AI API: {str(e)}")
            error_message = "Извините, у меня возникли проблемы с подключением к AI-сервису. Пожалуйста, попробуйте позже."
            self.add_message(session_id, 'assistant', error_message)
            raise ClaudeAIError(f"Error calling Claude AI API: {str(e)}")
    
    def analyze_planfix_data(self, session_id: str, query: str, data: Dict) -> str:
        """
        Analyze Planfix data using Claude AI.
        
        Args:
            session_id: ID of the chat session
            query: User query
            data: Planfix data to analyze
            
        Returns:
            Analysis result
        """
        # Prepare system prompt
        system_prompt = self._prepare_system_prompt(session_id)
        
        # Add specific instructions for data analysis
        system_prompt += """
        
        Вам предоставлены данные Planfix для анализа. 
        Предоставьте аналитическую информацию, ответьте на вопросы и извлеките соответствующую информацию из этих данных.
        Будьте конкретными, точными и сосредоточьтесь на фактах, представленных в данных.
        """
        
        # Convert data to string representation
        data_str = json.dumps(data, indent=2)
        
        # Create message for Claude
        messages = [
            {"role": "user", "content": f"Мне нужно, чтобы вы проанализировали следующие данные Planfix для ответа на вопрос: '{query}'\n\nДанные:\n```json\n{data_str}\n```"}
        ]
        
        # Call Claude AI API
        try:
            response = self.client.messages.create(
                model=self.model,
                max_tokens=self.max_tokens,
                system=system_prompt,
                messages=messages
            )
            
            # Extract the assistant's response
            analysis_result = response.content[0].text
            
            # Update AI context with information about this analysis
            self._update_ai_context(session_id, {
                'last_data_analysis': {
                    'query': query,
                    'timestamp': timezone.now().isoformat(),
                    'data_summary': f"Проанализировано {len(data)} элементов данных Planfix"
                }
            })
            
            return analysis_result
            
        except Exception as e:
            logger.error(f"Error analyzing Planfix data: {str(e)}")
            raise ClaudeAIError(f"Error analyzing Planfix data: {str(e)}")
    
    def generate_report(self, session_id: str, report_type: str, data: Dict) -> str:
        """
        Generate a report using Claude AI.
        
        Args:
            session_id: ID of the chat session
            report_type: Type of report to generate (project, task, summary, etc.)
            data: Data for the report
            
        Returns:
            Generated report
        """
        # Prepare system prompt
        system_prompt = self._prepare_system_prompt(session_id)
        
        # Add specific instructions for report generation
        system_prompt += f"""
        
        Вас просят создать отчет типа "{report_type}" на основе предоставленных данных.
        Создайте хорошо структурированный, профессиональный отчет с соответствующими разделами, выделенными моментами и аналитическими выводами.
        Используйте соответствующее форматирование, маркированные списки и заголовки, чтобы отчет было легко читать.
        """
        
        # Convert data to string representation
        data_str = json.dumps(data, indent=2)
        
        # Create message for Claude
        messages = [
            {"role": "user", "content": f"Пожалуйста, создайте отчет типа {report_type} на основе следующих данных:\n\n```json\n{data_str}\n```"}
        ]
        
        # Call Claude AI API
        try:
            response = self.client.messages.create(
                model=self.model,
                max_tokens=self.max_tokens,
                system=system_prompt,
                messages=messages
            )
            
            # Extract the assistant's response
            report = response.content[0].text
            
            return report
            
        except Exception as e:
            logger.error(f"Error generating report: {str(e)}")
            raise ClaudeAIError(f"Error generating report: {str(e)}")
    
    def parse_natural_language_query(self, session_id: str, query: str) -> Dict:
        """
        Parse a natural language query into a structured format.
        
        Args:
            session_id: ID of the chat session
            query: Natural language query
            
        Returns:
            Dictionary with parsed query structure
        """
        # Prepare system prompt
        system_prompt = self._prepare_system_prompt(session_id)
        
        # Add specific instructions for query parsing
        system_prompt += """
        
        Вас просят разобрать запрос на естественном языке в структурированный формат.
        Извлеките ключевые сущности, фильтры и параметры из запроса.
        Верните структурированное представление, которое можно использовать для запроса API Planfix.
        
        Ваш ответ должен быть в формате JSON со следующей структурой:
        {
            "intent": "tasks|projects|employees|comments|etc.",
            "filters": {
                "field1": "value1",
                "field2": "value2",
                ...
            },
            "sort": {
                "field": "field_name",
                "order": "asc|desc"
            },
            "limit": 10,
            "confidence": 0.95
        }
        """
        
        # Create message for Claude
        messages = [
            {"role": "user", "content": f"Разберите следующий запрос в структурированный формат: '{query}'"}
        ]
        
        # Call Claude AI API
        try:
            response = self.client.messages.create(
                model=self.model,
                max_tokens=1000,  # Lower token limit for structured output
                system=system_prompt,
                messages=messages
            )
            
            # Extract the assistant's response
            parsed_response = response.content[0].text
            
            # Try to extract JSON from the response
            try:
                # Find JSON part in the response
                import re
                json_match = re.search(r'```json\n(.*?)\n```', parsed_response, re.DOTALL)
                
                if json_match:
                    json_str = json_match.group(1)
                else:
                    # Try to find JSON without markdown code blocks
                    json_match = re.search(r'{.*}', parsed_response, re.DOTALL)
                    if json_match:
                        json_str = json_match.group(0)
                    else:
                        json_str = parsed_response
                
                parsed_query = json.loads(json_str)
                
                # Validate parsed query structure
                if 'intent' not in parsed_query:
                    parsed_query['intent'] = 'unknown'
                    
                if 'filters' not in parsed_query:
                    parsed_query['filters'] = {}
                    
                if 'confidence' not in parsed_query:
                    parsed_query['confidence'] = 0.7
                
                return parsed_query
                
            except json.JSONDecodeError:
                logger.error(f"Failed to parse JSON from Claude response: {parsed_response}")
                return {
                    "intent": "unknown",
                    "filters": {},
                    "error": "Failed to parse structured query",
                    "original_query": query,
                    "confidence": 0.0
                }
                
        except Exception as e:
            logger.error(f"Error parsing natural language query: {str(e)}")
            raise ClaudeAIError(f"Error parsing natural language query: {str(e)}")
    
    def rename_chat_session(self, session_id: str) -> str:
        """
        Generate a title for a chat session based on its content.
        
        Args:
            session_id: ID of the chat session
            
        Returns:
            Generated title
        """
        from core.models import ChatSession, ChatMessage
        
        try:
            session = ChatSession.objects.get(id=session_id)
            
            # Get the first user message
            first_message = session.messages.filter(role='user').first()
            
            if not first_message:
                return "Новая беседа"
            
            # Prepare system prompt
            system_prompt = """
            Вы являетесь помощником, который должен создать краткое, описательное название для беседы.
            Название должно быть лаконичным (5 слов или меньше) и отражать основную тему беседы.
            Отвечайте только названием, ничего больше.
            """
            
            # Create message for Claude
            messages = [
                {"role": "user", "content": f"Создайте короткое название для беседы, которая начинается с этого сообщения: '{first_message.content}'"}
            ]
            
            # Call Claude AI API
            response = self.client.messages.create(
                model=self.model,
                max_tokens=20,  # Very low token limit for just the title
                system=system_prompt,
                messages=messages
            )
            
            # Extract the assistant's response
            title = response.content[0].text.strip()
            
            # Remove quotes if present
            title = title.strip('"\'')
            
            # Truncate title if it's too long
            if len(title) > 50:
                title = title[:47] + "..."
            
            # Update session title
            session.title = title
            session.save()
            
            return title
            
        except Exception as e:
            logger.error(f"Error renaming chat session: {str(e)}")
            return "Новая беседа"
            
    def get_planfix_data_context(self, session_id: str, user_id: str) -> Dict:
        """
        Get context data from Planfix for a user to enhance Claude's responses.
        
        Args:
            session_id: ID of the chat session
            user_id: ID of the user
            
        Returns:
            Dictionary with context data
        """
        try:
            from core.planfix_api import PlanfixAPI
            from core.models import User
            
            user = User.objects.get(id=user_id)
            planfix_id = user.planfix_id
            
            if not planfix_id:
                return {}
                
            # Initialize Planfix API
            api = PlanfixAPI()
            
            # Get user's tasks and stats
            try:
                user_tasks = api.get_my_tasks(planfix_id, limit=10)
                user_stats = api.get_user_stats(planfix_id)
                
                # Format task information
                tasks_info = []
                for task in user_tasks:
                    task_info = {
                        'id': task.get('id'),
                        'title': task.get('title'),
                        'status': task.get('status', {}).get('name', 'Unknown'),
                        'deadline': task.get('deadline'),
                        'priority': task.get('priority', 2)  # Default to normal priority
                    }
                    tasks_info.append(task_info)
                
                # Update AI context with this information
                self._update_ai_context(session_id, {
                    'user_tasks': tasks_info,
                    'user_stats': user_stats
                })
                
                return {
                    'user_tasks': tasks_info,
                    'user_stats': user_stats
                }
                
            except Exception as e:
                logger.error(f"Error getting Planfix data for user {user_id}: {str(e)}")
                return {}
                
        except Exception as e:
            logger.error(f"Error getting Planfix data context: {str(e)}")
            return {}
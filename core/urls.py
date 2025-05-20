from django.urls import path
from django.views.generic import RedirectView

from core.views.auth_views import (
    LoginView, LogoutView, RegistrationView, ProfileView
)
from core.views.chat_views import (
    ChatHomeView, ChatSessionView, CreateChatSessionView, DeleteChatSessionView,
    ChatMessageView, ChatHistoryView, SearchChatView, SemanticSearchView,
    ProcessNaturalLanguageQueryView
)
from core.views.data_views import (
    DashboardView, TaskListView, TaskDetailView, ProjectListView, ProjectDetailView,
    FileDownloadView, UserListView, APIDataView, VectorDatabaseStatusView,
    TriggerDataSyncView, TriggerVectorUpdateView
)

# URL patterns for the application
urlpatterns = [
    # Home page - redirect to dashboard or chat based on role
    path('', RedirectView.as_view(pattern_name='chat_home'), name='home'),
    
    # Authentication URLs
    path('login/', LoginView.as_view(), name='login'),
    path('logout/', LogoutView.as_view(), name='logout'),
    path('register/', RegistrationView.as_view(), name='register'),
    path('profile/', ProfileView.as_view(), name='profile'),
    
    # Dashboard URLs
    path('dashboard/', DashboardView.as_view(), name='dashboard'),
    
    # Chat URLs
    path('chat/', ChatHomeView.as_view(), name='chat_home'),
    path('chat/new/', CreateChatSessionView.as_view(), name='create_chat'),
    path('chat/new/<uuid:session_id>/', CreateChatSessionView.as_view(), name='create_chat_with_id'),
    path('chat/session/<uuid:session_id>/', ChatSessionView.as_view(), name='chat_session'),
    path('chat/session/<uuid:session_id>/delete/', DeleteChatSessionView.as_view(), name='delete_chat'),
    path('chat/message/', ChatMessageView.as_view(), name='chat_message'),
    path('chat/history/', ChatHistoryView.as_view(), name='chat_history'),
    path('chat/search/', SearchChatView.as_view(), name='search_chat'),
    path('chat/semantic-search/', SemanticSearchView.as_view(), name='semantic_search'),
    path('chat/nlp-query/', ProcessNaturalLanguageQueryView.as_view(), name='nlp_query'),
    
    # Task URLs
    path('tasks/', TaskListView.as_view(), name='task_list'),
    path('tasks/<int:task_id>/', TaskDetailView.as_view(), name='task_detail'),
    
    # Project URLs
    path('projects/', ProjectListView.as_view(), name='project_list'),
    path('projects/<int:project_id>/', ProjectDetailView.as_view(), name='project_detail'),
    
    # User URLs
    path('users/', UserListView.as_view(), name='user_list'),
    
    # File URLs
    path('files/<int:file_id>/', FileDownloadView.as_view(), name='file_download'),
    
    # API Data URLs
    path('api/data/<str:data_type>/', APIDataView.as_view(), name='api_data'),
    path('api/data/<str:data_type>/<str:item_id>/', APIDataView.as_view(), name='api_data_item'),
    
    # Vector Database URLs
    path('api/vector-db/status/', VectorDatabaseStatusView.as_view(), name='vector_db_status'),
    
    # Admin Actions URLs
    path('api/trigger-sync/', TriggerDataSyncView.as_view(), name='trigger_sync'),
    path('api/trigger-vector-update/', TriggerVectorUpdateView.as_view(), name='trigger_vector_update'),
]
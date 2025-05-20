import logging
from django.shortcuts import render, redirect
from django.urls import reverse_lazy, reverse
from django.views.generic import FormView, RedirectView, TemplateView, View
from django.contrib.auth import login, logout, authenticate
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib import messages
from django.utils import timezone
from django.utils.translation import gettext_lazy as _
from django.conf import settings

from core.forms import LoginForm, RegistrationForm, ProfileUpdateForm
from core.models import User, LogEntry

logger = logging.getLogger(__name__)


class LoginView(FormView):
    """View for user login."""
    
    template_name = 'auth/login.html'
    form_class = LoginForm
    success_url = reverse_lazy('home')
    
    def get(self, request, *args, **kwargs):
        # Redirect to home if user is already authenticated
        if request.user.is_authenticated:
            return redirect('home')
        return super().get(request, *args, **kwargs)
    
    def form_valid(self, form):
        username = form.cleaned_data.get('username')
        password = form.cleaned_data.get('password')
        
        user = authenticate(username=username, password=password)
        
        if user is not None:
            # Log the user in
            login(self.request, user)
            
            # Update last active timestamp
            user.save_last_active()
            
            # Log login event
            LogEntry.objects.create(
                user=user,
                level='INFO',
                source='auth',
                message=f'User {username} logged in',
                metadata={
                    'ip': self.request.META.get('REMOTE_ADDR'),
                    'user_agent': self.request.META.get('HTTP_USER_AGENT', '')
                }
            )
            
            # Check if user was redirected from another page
            next_url = self.request.GET.get('next')
            if next_url:
                return redirect(next_url)
            
            return super().form_valid(form)
        else:
            # Log failed login attempt
            LogEntry.objects.create(
                level='WARNING',
                source='auth',
                message=f'Failed login attempt for username {username}',
                metadata={
                    'ip': self.request.META.get('REMOTE_ADDR'),
                    'user_agent': self.request.META.get('HTTP_USER_AGENT', '')
                }
            )
            
            # Add error message
            messages.error(self.request, _('Invalid username or password. Please try again.'))
            return self.form_invalid(form)


class LogoutView(RedirectView):
    """View for user logout."""
    
    url = reverse_lazy('login')
    
    def get(self, request, *args, **kwargs):
        if request.user.is_authenticated:
            username = request.user.username
            
            # Log logout event
            LogEntry.objects.create(
                user=request.user,
                level='INFO',
                source='auth',
                message=f'User {username} logged out',
                metadata={
                    'ip': request.META.get('REMOTE_ADDR'),
                    'user_agent': request.META.get('HTTP_USER_AGENT', '')
                }
            )
            
            # Logout the user
            logout(request)
            
            # Add success message
            messages.success(request, _('You have been successfully logged out.'))
        
        return super().get(request, *args, **kwargs)


class RegistrationView(FormView):
    """View for user registration."""
    
    template_name = 'auth/register.html'
    form_class = RegistrationForm
    success_url = reverse_lazy('login')
    
    def get(self, request, *args, **kwargs):
        # Redirect to home if user is already authenticated
        if request.user.is_authenticated:
            return redirect('home')
        return super().get(request, *args, **kwargs)
    
    def form_valid(self, form):
        # Create new user
        user = form.save(commit=False)
        user.role = 'collaborator'  # Default role
        user.set_password(form.cleaned_data['password1'])
        user.save()
        
        # Log registration event
        LogEntry.objects.create(
            user=user,
            level='INFO',
            source='auth',
            message=f'New user {user.username} registered',
            metadata={
                'ip': self.request.META.get('REMOTE_ADDR'),
                'user_agent': self.request.META.get('HTTP_USER_AGENT', '')
            }
        )
        
        # Add success message
        messages.success(self.request, _('Registration successful. You can now log in.'))
        
        return super().form_valid(form)


class ProfileView(LoginRequiredMixin, FormView):
    """View for user profile."""
    
    template_name = 'auth/profile.html'
    form_class = ProfileUpdateForm
    success_url = reverse_lazy('profile')
    
    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['instance'] = self.request.user
        return kwargs
    
    def form_valid(self, form):
        # Update user profile
        user = form.save(commit=False)
        
        # Check if password is being changed
        if form.cleaned_data.get('password1'):
            user.set_password(form.cleaned_data['password1'])
        
        user.save()
        
        # Log profile update event
        LogEntry.objects.create(
            user=user,
            level='INFO',
            source='auth',
            message=f'User {user.username} updated profile',
            metadata={
                'ip': self.request.META.get('REMOTE_ADDR'),
                'user_agent': self.request.META.get('HTTP_USER_AGENT', '')
            }
        )
        
        # Add success message
        messages.success(self.request, _('Profile updated successfully.'))
        
        # If password was changed, log the user out
        if form.cleaned_data.get('password1'):
            logout(self.request)
            messages.info(self.request, _('Password changed. Please log in with your new password.'))
            return redirect('login')
        
        return super().form_valid(form)
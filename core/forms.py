from django import forms
from django.contrib.auth.forms import UserCreationForm, AuthenticationForm
from django.utils.translation import gettext_lazy as _

from core.models import User, Task, Project, Comment


class LoginForm(AuthenticationForm):
    """Form for user login."""
    
    username = forms.CharField(
        widget=forms.TextInput(
            attrs={
                'class': 'w-full px-3 py-2 placeholder-gray-400 border border-gray-300 rounded-md focus:outline-none focus:ring-indigo-500 focus:border-indigo-500',
                'placeholder': _('Username or Email'),
                'required': True,
            }
        )
    )
    
    password = forms.CharField(
        widget=forms.PasswordInput(
            attrs={
                'class': 'w-full px-3 py-2 placeholder-gray-400 border border-gray-300 rounded-md focus:outline-none focus:ring-indigo-500 focus:border-indigo-500',
                'placeholder': _('Password'),
                'required': True,
            }
        )
    )


class RegistrationForm(UserCreationForm):
    """Form for user registration."""
    
    email = forms.EmailField(
        required=True,
        widget=forms.EmailInput(
            attrs={
                'class': 'w-full px-3 py-2 placeholder-gray-400 border border-gray-300 rounded-md focus:outline-none focus:ring-indigo-500 focus:border-indigo-500',
                'placeholder': _('Email Address'),
            }
        )
    )
    
    first_name = forms.CharField(
        required=True,
        widget=forms.TextInput(
            attrs={
                'class': 'w-full px-3 py-2 placeholder-gray-400 border border-gray-300 rounded-md focus:outline-none focus:ring-indigo-500 focus:border-indigo-500',
                'placeholder': _('First Name'),
            }
        )
    )
    
    last_name = forms.CharField(
        required=True,
        widget=forms.TextInput(
            attrs={
                'class': 'w-full px-3 py-2 placeholder-gray-400 border border-gray-300 rounded-md focus:outline-none focus:ring-indigo-500 focus:border-indigo-500',
                'placeholder': _('Last Name'),
            }
        )
    )
    
    password1 = forms.CharField(
        label=_('Password'),
        widget=forms.PasswordInput(
            attrs={
                'class': 'w-full px-3 py-2 placeholder-gray-400 border border-gray-300 rounded-md focus:outline-none focus:ring-indigo-500 focus:border-indigo-500',
                'placeholder': _('Password'),
            }
        )
    )
    
    password2 = forms.CharField(
        label=_('Confirm Password'),
        widget=forms.PasswordInput(
            attrs={
                'class': 'w-full px-3 py-2 placeholder-gray-400 border border-gray-300 rounded-md focus:outline-none focus:ring-indigo-500 focus:border-indigo-500',
                'placeholder': _('Confirm Password'),
            }
        )
    )
    
    language_preference = forms.ChoiceField(
        choices=[('en', _('English')), ('ru', _('Russian'))],
        required=True,
        widget=forms.Select(
            attrs={
                'class': 'w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-indigo-500 focus:border-indigo-500',
            }
        )
    )
    
    class Meta:
        model = User
        fields = (
            'username', 'email', 'first_name', 'last_name',
            'password1', 'password2', 'language_preference'
        )
        widgets = {
            'username': forms.TextInput(
                attrs={
                    'class': 'w-full px-3 py-2 placeholder-gray-400 border border-gray-300 rounded-md focus:outline-none focus:ring-indigo-500 focus:border-indigo-500',
                    'placeholder': _('Username'),
                }
            ),
        }


class ProfileUpdateForm(forms.ModelForm):
    """Form for updating user profile."""
    
    password1 = forms.CharField(
        label=_('New Password'),
        required=False,
        widget=forms.PasswordInput(
            attrs={
                'class': 'w-full px-3 py-2 placeholder-gray-400 border border-gray-300 rounded-md focus:outline-none focus:ring-indigo-500 focus:border-indigo-500',
                'placeholder': _('New Password (optional)'),
            }
        )
    )
    
    password2 = forms.CharField(
        label=_('Confirm New Password'),
        required=False,
        widget=forms.PasswordInput(
            attrs={
                'class': 'w-full px-3 py-2 placeholder-gray-400 border border-gray-300 rounded-md focus:outline-none focus:ring-indigo-500 focus:border-indigo-500',
                'placeholder': _('Confirm New Password'),
            }
        )
    )
    
    class Meta:
        model = User
        fields = (
            'first_name', 'last_name', 'email', 'language_preference', 'profile_image'
        )
        widgets = {
            'first_name': forms.TextInput(
                attrs={
                    'class': 'w-full px-3 py-2 placeholder-gray-400 border border-gray-300 rounded-md focus:outline-none focus:ring-indigo-500 focus:border-indigo-500',
                }
            ),
            'last_name': forms.TextInput(
                attrs={
                    'class': 'w-full px-3 py-2 placeholder-gray-400 border border-gray-300 rounded-md focus:outline-none focus:ring-indigo-500 focus:border-indigo-500',
                }
            ),
            'email': forms.EmailInput(
                attrs={
                    'class': 'w-full px-3 py-2 placeholder-gray-400 border border-gray-300 rounded-md focus:outline-none focus:ring-indigo-500 focus:border-indigo-500',
                }
            ),
            'language_preference': forms.Select(
                attrs={
                    'class': 'w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-indigo-500 focus:border-indigo-500',
                }
            ),
            'profile_image': forms.FileInput(
                attrs={
                    'class': 'w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-indigo-500 focus:border-indigo-500',
                }
            ),
        }
    
    def clean(self):
        cleaned_data = super().clean()
        password1 = cleaned_data.get('password1')
        password2 = cleaned_data.get('password2')
        
        if password1 and password1 != password2:
            self.add_error('password2', _('Passwords do not match'))
        
        return cleaned_data


class CommentForm(forms.ModelForm):
    """Form for adding a comment to a task."""
    
    class Meta:
        model = Comment
        fields = ('text',)
        widgets = {
            'text': forms.Textarea(
                attrs={
                    'class': 'w-full px-3 py-2 placeholder-gray-400 border border-gray-300 rounded-md focus:outline-none focus:ring-indigo-500 focus:border-indigo-500',
                    'placeholder': _('Add a comment...'),
                    'rows': 3,
                }
            ),
        }


class ChatMessageForm(forms.Form):
    """Form for sending a chat message."""
    
    message = forms.CharField(
        widget=forms.Textarea(
            attrs={
                'class': 'w-full px-3 py-2 placeholder-gray-400 border border-gray-300 rounded-md focus:outline-none focus:ring-indigo-500 focus:border-indigo-500',
                'placeholder': _('Type your message...'),
                'rows': 3,
            }
        )
    )


class SearchForm(forms.Form):
    """Form for searching."""
    
    q = forms.CharField(
        required=True,
        widget=forms.TextInput(
            attrs={
                'class': 'w-full px-3 py-2 placeholder-gray-400 border border-gray-300 rounded-md focus:outline-none focus:ring-indigo-500 focus:border-indigo-500',
                'placeholder': _('Search...'),
            }
        )
    )
    
    type = forms.ChoiceField(
        choices=[
            ('all', _('All')),
            ('task', _('Tasks')),
            ('project', _('Projects')),
            ('comment', _('Comments')),
        ],
        required=False,
        widget=forms.Select(
            attrs={
                'class': 'w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-indigo-500 focus:border-indigo-500',
            }
        )
    )
# Intelligent Assistant

A comprehensive Django application that integrates with Planfix and Claude AI to provide an intelligent assistant for project and task management.

## Features

- **Chat Interface**: Interact with Claude AI to get answers about your Planfix data
- **Data Integration**: Sync and manage tasks, projects, and users from Planfix
- **Vector Search**: Use semantic search to find relevant information quickly
- **Dashboard**: Get an overview of your tasks, projects, and system status
- **Role-Based Access**: Different access levels for administrators, managers, and collaborators
- **Multilingual Support**: Available in both English and Russian

## Tech Stack

- **Backend**: Django 5.0+
- **Database**: PostgreSQL
- **Vector Database**: FAISS
- **AI Integration**: Anthropic Claude API
- **Frontend**: Tailwind CSS, Alpine.js
- **API Integration**: Planfix API

## Getting Started

### Prerequisites

- Python 3.10+
- PostgreSQL 12+
- Node.js and npm (for Tailwind CSS)
- Planfix account with API access
- Anthropic API key for Claude AI

### Installation

1. Clone the repository:

```bash
git clone https://github.com/yourusername/intelligent-assistant.git
cd intelligent-assistant
```

2. Create a virtual environment and install dependencies:

```bash
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
pip install -r requirements.txt
```

3. Configure environment variables:
   
   Copy the `.env.example` file to `.env` and fill in your configuration values:

```bash
cp .env.example .env
# Edit .env with your database, Planfix, and Claude AI credentials
```

4. Setup the database:

```bash
python manage.py migrate
```

5. Create a superuser:

```bash
python manage.py createsuperuser
```

6. Install and compile Tailwind CSS:

```bash
npm install
npm run build:css
```

7. Run the development server:

```bash
python manage.py runserver
```

8. Initialize data:

```bash
# Sync data from Planfix
python manage.py sync_planfix_data

# Initialize vector database
python manage.py update_vector_db
```

## Usage

### Chat Interface

The chat interface allows users to interact with Claude AI to ask questions about their Planfix data. Examples of questions that can be asked:

- "What tasks are due today?"
- "Who is responsible for project X?"
- "What tasks are currently in 'In Approval' status?"
- "Generate a summary of project X from last week"

### Dashboard

The dashboard provides an overview of your tasks, projects, and system status. It includes:

- Task statistics (total, overdue, priority distribution)
- Project statistics
- User statistics
- Vector database status

### Admin Tools

Admin tools are available for system administrators to:

- Synchronize data from Planfix
- Manage the vector database
- Monitor system status

## Security Considerations

- All sensitive data (API keys, access tokens) is stored in environment variables
- HTTPS is required for production deployments
- Role-based access control restricts access to features based on user roles
- Authentication is required for all pages except login and registration
- Logging of AI access and user actions
- Protection against SQL injection, XSS, and CSRF with standard Django tools

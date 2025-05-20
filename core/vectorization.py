import os
import json
import logging
import numpy as np
import faiss
import pickle
from pathlib import Path
from typing import Dict, List, Tuple, Any, Optional, Union
from sentence_transformers import SentenceTransformer
from datetime import datetime

from django.conf import settings
from django.utils import timezone
from django.db.models import Q

logger = logging.getLogger(__name__)


class VectorizationError(Exception):
    """Custom exception for vectorization errors."""
    pass


class Vectorizer:
    """Class to handle vectorization of Planfix data."""
    
    def __init__(self):
        self.vector_db_type = getattr(settings, 'VECTOR_DB_TYPE', 'FAISS')
        self.vector_db_path = getattr(settings, 'VECTOR_DB_PATH', './vector_db')
        self.model_name = getattr(settings, 'EMBEDDING_MODEL', 'all-MiniLM-L6-v2')
        
        # Create vector_db directory if it doesn't exist
        Path(self.vector_db_path).mkdir(parents=True, exist_ok=True)
        
        # Load embedding model
        try:
            self.model = SentenceTransformer(self.model_name)
            self.vector_dim = self.model.get_sentence_embedding_dimension()
            logger.info(f"Loaded embedding model {self.model_name} with dimension {self.vector_dim}")
        except Exception as e:
            logger.error(f"Error loading embedding model: {str(e)}")
            raise VectorizationError(f"Error loading embedding model: {str(e)}")
        
        # Initialize vector database
        self._initialize_vector_database()
    
    def _initialize_vector_database(self) -> None:
        """Initialize the vector database."""
        if self.vector_db_type == 'FAISS':
            self._initialize_faiss()
        else:
            raise VectorizationError(f"Unsupported vector database type: {self.vector_db_type}")
    
    def _initialize_faiss(self) -> None:
        """Initialize FAISS vector database."""
        # Check if index exists
        index_path = os.path.join(self.vector_db_path, 'faiss_index.bin')
        metadata_path = os.path.join(self.vector_db_path, 'metadata.pkl')
        
        if os.path.exists(index_path) and os.path.exists(metadata_path):
            # Load existing index and metadata
            try:
                self.index = faiss.read_index(index_path)
                with open(metadata_path, 'rb') as f:
                    self.metadata = pickle.load(f)
                logger.info(f"Loaded existing FAISS index with {self.index.ntotal} vectors")
            except Exception as e:
                logger.error(f"Error loading existing FAISS index: {str(e)}")
                self._create_new_faiss_index()
        else:
            # Create new index and metadata
            self._create_new_faiss_index()
    
    def _create_new_faiss_index(self) -> None:
        """Create a new FAISS index."""
        try:
            # Create a new FAISS index
            self.index = faiss.IndexFlatL2(self.vector_dim)
            
            # Initialize metadata
            self.metadata = {
                'vectors': [],
                'created_at': timezone.now().isoformat(),
                'updated_at': timezone.now().isoformat(),
                'count': 0
            }
            
            logger.info("Created new FAISS index")
            
            # Save index and metadata
            self._save_faiss_index()
            
            # Update database statistics
            from core.models import VectorDBMetadata
            VectorDBMetadata.objects.update_or_create(
                defaults={
                    'total_vectors': 0,
                    'tasks_indexed': 0,
                    'projects_indexed': 0,
                    'comments_indexed': 0,
                    'index_status': 'initialized'
                }
            )
            
        except Exception as e:
            logger.error(f"Error creating new FAISS index: {str(e)}")
            raise VectorizationError(f"Error creating new FAISS index: {str(e)}")
    
    def _save_faiss_index(self) -> None:
        """Save FAISS index and metadata to disk."""
        try:
            index_path = os.path.join(self.vector_db_path, 'faiss_index.bin')
            metadata_path = os.path.join(self.vector_db_path, 'metadata.pkl')
            
            # Save index
            faiss.write_index(self.index, index_path)
            
            # Save metadata
            with open(metadata_path, 'wb') as f:
                pickle.dump(self.metadata, f)
            
            logger.info(f"Saved FAISS index with {self.index.ntotal} vectors")
            
        except Exception as e:
            logger.error(f"Error saving FAISS index: {str(e)}")
            raise VectorizationError(f"Error saving FAISS index: {str(e)}")
    
    def _get_embedding(self, text: str) -> np.ndarray:
        """
        Get embedding for a text.
        
        Args:
            text: Text to embed
            
        Returns:
            Embedding vector
        """
        try:
            # Clean text
            clean_text = text.strip()
            if not clean_text:
                clean_text = "Empty text"
            
            # Get embedding
            embedding = self.model.encode(clean_text)
            
            return embedding
        except Exception as e:
            logger.error(f"Error getting embedding: {str(e)}")
            raise VectorizationError(f"Error getting embedding: {str(e)}")
    
    def add_vector(self, text: str, metadata: Dict) -> int:
        """
        Add a vector to the database.
        
        Args:
            text: Text to vectorize
            metadata: Metadata for the vector
            
        Returns:
            Vector ID
        """
        if self.vector_db_type == 'FAISS':
            return self._add_vector_faiss(text, metadata)
        else:
            raise VectorizationError(f"Unsupported vector database type: {self.vector_db_type}")
    
    def _add_vector_faiss(self, text: str, metadata: Dict) -> int:
        """
        Add a vector to FAISS.
        
        Args:
            text: Text to vectorize
            metadata: Metadata for the vector
            
        Returns:
            Vector ID
        """
        try:
            # Get embedding
            embedding = self._get_embedding(text)
            
            # Add vector to FAISS
            embedding_np = np.array([embedding], dtype=np.float32)
            
            # Get current count as vector ID
            vector_id = self.metadata['count']
            
            # Add to FAISS index
            self.index.add(embedding_np)
            
            # Add metadata
            self.metadata['vectors'].append({
                'id': vector_id,
                'text': text[:200] + ('...' if len(text) > 200 else ''),  # Store truncated text
                'metadata': metadata,
                'created_at': timezone.now().isoformat()
            })
            
            # Update count
            self.metadata['count'] += 1
            self.metadata['updated_at'] = timezone.now().isoformat()
            
            # Save index and metadata every 100 additions
            if vector_id % 100 == 0:
                self._save_faiss_index()
            
            return vector_id
            
        except Exception as e:
            logger.error(f"Error adding vector to FAISS: {str(e)}")
            raise VectorizationError(f"Error adding vector to FAISS: {str(e)}")
    
    def search(self, query: str, top_k: int = 5) -> List[Dict]:
        """
        Search for similar vectors.
        
        Args:
            query: Query text
            top_k: Number of results to return
            
        Returns:
            List of search results with metadata
        """
        if self.vector_db_type == 'FAISS':
            return self._search_faiss(query, top_k)
        else:
            raise VectorizationError(f"Unsupported vector database type: {self.vector_db_type}")
    
    def _search_faiss(self, query: str, top_k: int = 5) -> List[Dict]:
        """
        Search for similar vectors in FAISS.
        
        Args:
            query: Query text
            top_k: Number of results to return
            
        Returns:
            List of search results with metadata
        """
        try:
            # Get query embedding
            query_embedding = self._get_embedding(query)
            query_embedding_np = np.array([query_embedding], dtype=np.float32)
            
            # Check if index is empty
            if self.index.ntotal == 0:
                return []
            
            # Search FAISS index
            distances, indices = self.index.search(query_embedding_np, min(top_k, self.index.ntotal))
            
            # Get results with metadata
            results = []
            for i, idx in enumerate(indices[0]):
                if idx >= 0:  # FAISS may return -1 for not enough results
                    metadata_entry = next((item for item in self.metadata['vectors'] if item['id'] == idx), None)
                    if metadata_entry:
                        results.append({
                            'id': metadata_entry['id'],
                            'text': metadata_entry['text'],
                            'metadata': metadata_entry['metadata'],
                            'distance': float(distances[0][i]),
                            'similarity': 1.0 / (1.0 + float(distances[0][i]))  # Convert distance to similarity
                        })
            
            return results
            
        except Exception as e:
            logger.error(f"Error searching FAISS: {str(e)}")
            raise VectorizationError(f"Error searching FAISS: {str(e)}")
    
    def delete_vector(self, vector_id: int) -> bool:
        """
        Delete a vector from the database.
        
        Args:
            vector_id: ID of the vector to delete
            
        Returns:
            True if successful, False otherwise
        """
        if self.vector_db_type == 'FAISS':
            return self._delete_vector_faiss(vector_id)
        else:
            raise VectorizationError(f"Unsupported vector database type: {self.vector_db_type}")
    
    def _delete_vector_faiss(self, vector_id: int) -> bool:
        """
        Delete a vector from FAISS.
        
        Note: FAISS doesn't support direct deletion, so we rebuild the index without the deleted vector.
        
        Args:
            vector_id: ID of the vector to delete
            
        Returns:
            True if successful, False otherwise
        """
        try:
            # Check if vector exists
            vector_exists = any(item['id'] == vector_id for item in self.metadata['vectors'])
            
            if not vector_exists:
                logger.warning(f"Vector ID {vector_id} not found in metadata")
                return False
            
            # Filter out the vector to delete
            filtered_vectors = [item for item in self.metadata['vectors'] if item['id'] != vector_id]
            
            # Create a new index
            new_index = faiss.IndexFlatL2(self.vector_dim)
            
            # Add remaining vectors to the new index
            for item in filtered_vectors:
                # We need to re-encode the text since we don't store the actual vectors in metadata
                embedding = self._get_embedding(item['text'])
                embedding_np = np.array([embedding], dtype=np.float32)
                new_index.add(embedding_np)
            
            # Update metadata
            self.metadata['vectors'] = filtered_vectors
            self.metadata['updated_at'] = timezone.now().isoformat()
            
            # Replace old index with new index
            self.index = new_index
            
            # Save updated index and metadata
            self._save_faiss_index()
            
            return True
            
        except Exception as e:
            logger.error(f"Error deleting vector from FAISS: {str(e)}")
            raise VectorizationError(f"Error deleting vector from FAISS: {str(e)}")
    
    def update_vector(self, vector_id: int, text: str, metadata: Dict) -> bool:
        """
        Update a vector in the database.
        
        Args:
            vector_id: ID of the vector to update
            text: New text
            metadata: New metadata
            
        Returns:
            True if successful, False otherwise
        """
        # For simplicity, we delete and re-add the vector
        try:
            # Delete old vector
            deleted = self.delete_vector(vector_id)
            
            if not deleted:
                logger.warning(f"Failed to delete vector ID {vector_id} for update")
                return False
            
            # Add new vector with same ID
            # We need to manually set the ID in metadata
            self.metadata['count'] -= 1  # Decrement count to reuse the same ID
            new_id = self.add_vector(text, metadata)
            
            if new_id != vector_id:
                logger.warning(f"Vector ID mismatch during update: expected {vector_id}, got {new_id}")
                return False
            
            return True
            
        except Exception as e:
            logger.error(f"Error updating vector: {str(e)}")
            raise VectorizationError(f"Error updating vector: {str(e)}")
    
    def vectorize_planfix_data(self) -> Dict:
        """
        Vectorize all Planfix data.
        
        Returns:
            Dictionary with statistics about vectorized data
        """
        from core.models import Task, Project, Comment, VectorDBMetadata
        
        stats = {
            'tasks': 0,
            'projects': 0,
            'comments': 0,
            'errors': []
        }
        
        try:
            # Update index status
            VectorDBMetadata.objects.update_or_create(
                defaults={'index_status': 'indexing'}
            )
            
            # Vectorize tasks
            for task in Task.objects.filter(vector_id__isnull=True):
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
                    vector_id = self.add_vector(task_text, metadata)
                    
                    # Update task with vector ID
                    task.vector_id = str(vector_id)
                    task.save(update_fields=['vector_id'])
                    
                    stats['tasks'] += 1
                    
                except Exception as e:
                    logger.error(f"Error vectorizing task {task.id}: {str(e)}")
                    stats['errors'].append(f"Task {task.id}: {str(e)}")
            
            # Vectorize projects
            for project in Project.objects.filter(vector_id__isnull=True):
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
                    vector_id = self.add_vector(project_text, metadata)
                    
                    # Update project with vector ID
                    project.vector_id = str(vector_id)
                    project.save(update_fields=['vector_id'])
                    
                    stats['projects'] += 1
                    
                except Exception as e:
                    logger.error(f"Error vectorizing project {project.id}: {str(e)}")
                    stats['errors'].append(f"Project {project.id}: {str(e)}")
            
            # Vectorize comments
            for comment in Comment.objects.filter(vector_id__isnull=True):
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
                    vector_id = self.add_vector(comment_text, metadata)
                    
                    # Update comment with vector ID
                    comment.vector_id = str(vector_id)
                    comment.save(update_fields=['vector_id'])
                    
                    stats['comments'] += 1
                    
                except Exception as e:
                    logger.error(f"Error vectorizing comment {comment.id}: {str(e)}")
                    stats['errors'].append(f"Comment {comment.id}: {str(e)}")
            
            # Save index and metadata
            self._save_faiss_index()
            
            # Update database statistics
            VectorDBMetadata.objects.update_or_create(
                defaults={
                    'total_vectors': self.index.ntotal,
                    'tasks_indexed': Task.objects.filter(vector_id__isnull=False).count(),
                    'projects_indexed': Project.objects.filter(vector_id__isnull=False).count(),
                    'comments_indexed': Comment.objects.filter(vector_id__isnull=False).count(),
                    'index_status': 'ready'
                }
            )
            
            return stats
            
        except Exception as e:
            logger.error(f"Error vectorizing Planfix data: {str(e)}")
            
            # Update database statistics
            VectorDBMetadata.objects.update_or_create(
                defaults={'index_status': 'error'}
            )
            
            stats['errors'].append(str(e))
            return stats
    
    def semantic_search(self, query: str, filter_type: str = None, top_k: int = 5) -> List[Dict]:
        """
        Perform semantic search with optional type filtering.
        
        Args:
            query: Query text
            filter_type: Optional type filter ('task', 'project', 'comment')
            top_k: Number of results to return
            
        Returns:
            List of search results with metadata
        """
        try:
            # Perform basic search
            results = self.search(query, top_k=top_k * 2)  # Get more results for filtering
            
            # Apply type filter if specified
            if filter_type:
                results = [r for r in results if r['metadata'].get('type') == filter_type]
            
            # Sort by similarity
            results = sorted(results, key=lambda r: r['similarity'], reverse=True)
            
            # Limit to top_k
            results = results[:top_k]
            
            return results
            
        except Exception as e:
            logger.error(f"Error performing semantic search: {str(e)}")
            raise VectorizationError(f"Error performing semantic search: {str(e)}")
            
    def get_vector_database_stats(self) -> Dict:
        """
        Get statistics about the vector database.
        
        Returns:
            Dictionary with vector database statistics
        """
        try:
            # Get vector count by type
            type_counts = {}
            for v in self.metadata['vectors']:
                v_type = v['metadata'].get('type')
                if v_type:
                    type_counts[v_type] = type_counts.get(v_type, 0) + 1
            
            # Get index size on disk
            index_path = os.path.join(self.vector_db_path, 'faiss_index.bin')
            metadata_path = os.path.join(self.vector_db_path, 'metadata.pkl')
            
            index_size = os.path.getsize(index_path) if os.path.exists(index_path) else 0
            metadata_size = os.path.getsize(metadata_path) if os.path.exists(metadata_path) else 0
            
            # Format stats
            stats = {
                'total_vectors': self.index.ntotal,
                'dimensions': self.vector_dim,
                'vector_db_type': self.vector_db_type,
                'model_name': self.model_name,
                'created_at': self.metadata.get('created_at'),
                'updated_at': self.metadata.get('updated_at'),
                'type_counts': type_counts,
                'disk_space': {
                    'index_size_bytes': index_size,
                    'metadata_size_bytes': metadata_size,
                    'total_size_bytes': index_size + metadata_size,
                    'total_size_mb': round((index_size + metadata_size) / (1024 * 1024), 2)
                }
            }
            
            return stats
            
        except Exception as e:
            logger.error(f"Error getting vector database stats: {str(e)}")
            raise VectorizationError(f"Error getting vector database stats: {str(e)}")
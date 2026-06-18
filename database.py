"""
Database Manager for Recipe Digitization System
Handles SQLite database operations with duplicate detection
"""

import sqlite3
import json
import hashlib
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from datetime import datetime
from dataclasses import dataclass, asdict


@dataclass
class Cookbook:
    """Cookbook metadata"""
    id: Optional[int] = None
    name: str = ""
    authors: str = ""  # JSON array as string
    language: str = "en"
    cuisine: str = ""
    config_path: str = ""
    created_at: Optional[str] = None


@dataclass
class Recipe:
    """Recipe data model"""
    id: Optional[int] = None
    cookbook_id: Optional[int] = None
    title: str = ""
    page_number: Optional[int] = None
    image_hash: str = ""
    image_path: str = ""
    
    # Recipe content (stored as JSON in DB)
    ingredients: List[str] = None
    instructions: List[str] = None
    background_info: str = ""
    handwritten_notes: str = ""
    
    # Metadata
    prep_time: str = ""
    cook_time: str = ""
    total_time: str = ""
    servings: str = ""
    tags: List[str] = None
    cuisine: str = ""
    
    # Tracking
    processed_at: Optional[str] = None
    markdown_path: str = ""
    mealie_id: Optional[str] = None
    mealie_synced_at: Optional[str] = None
    mealie_synced_hash: Optional[str] = None  # fingerprint of content at last sync

    # Quality
    ocr_confidence: Optional[float] = None

    def __post_init__(self):
        if self.ingredients is None:
            self.ingredients = []
        if self.instructions is None:
            self.instructions = []
        if self.tags is None:
            self.tags = []

    def content_fingerprint(self) -> str:
        """
        SHA256 of the fields that get pushed to Mealie. Used to detect whether a
        recipe changed since its last sync (compare against mealie_synced_hash).
        """
        payload = json.dumps({
            'title': self.title,
            'ingredients': self.ingredients,
            'instructions': self.instructions,
            'background_info': self.background_info,
            'handwritten_notes': self.handwritten_notes,
            'prep_time': self.prep_time,
            'cook_time': self.cook_time,
            'total_time': self.total_time,
            'servings': self.servings,
            'tags': self.tags,
            'cuisine': self.cuisine,
        }, sort_keys=True, ensure_ascii=False)
        return hashlib.sha256(payload.encode('utf-8')).hexdigest()


class DatabaseManager:
    """Manages SQLite database for recipe storage"""
    
    def __init__(self, db_path: str = "recipes.db"):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.init_database()
    
    def get_connection(self) -> sqlite3.Connection:
        """Get database connection"""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row  # Access columns by name
        return conn
    
    def init_database(self):
        """Initialize database schema"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        # Cookbooks table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS cookbooks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE,
                authors TEXT,
                language TEXT DEFAULT 'en',
                cuisine TEXT,
                config_path TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # Recipes table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS recipes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                cookbook_id INTEGER,
                title TEXT NOT NULL,
                page_number INTEGER,
                image_hash TEXT UNIQUE,
                image_path TEXT,
                
                ingredients TEXT,
                instructions TEXT,
                background_info TEXT,
                handwritten_notes TEXT,
                
                prep_time TEXT,
                cook_time TEXT,
                total_time TEXT,
                servings TEXT,
                tags TEXT,
                cuisine TEXT,
                
                processed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                markdown_path TEXT,
                mealie_id TEXT,
                mealie_synced_at TIMESTAMP,
                
                ocr_confidence REAL,
                
                FOREIGN KEY (cookbook_id) REFERENCES cookbooks(id)
            )
        """)
        
        # Processing log
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS processing_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                image_path TEXT,
                image_hash TEXT,
                status TEXT,
                error_message TEXT,
                processed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # Create indexes
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_recipes_cookbook 
            ON recipes(cookbook_id)
        """)
        
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_recipes_image_hash 
            ON recipes(image_hash)
        """)
        
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_recipes_mealie_id 
            ON recipes(mealie_id)
        """)
        
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_processing_log_hash
            ON processing_log(image_hash)
        """)

        # Migration: add mealie_synced_hash to pre-existing databases
        cursor.execute("PRAGMA table_info(recipes)")
        existing_columns = {row[1] for row in cursor.fetchall()}
        if 'mealie_synced_hash' not in existing_columns:
            cursor.execute("ALTER TABLE recipes ADD COLUMN mealie_synced_hash TEXT")

        conn.commit()
        conn.close()
    
    # ==================== Cookbook Operations ====================
    
    def add_cookbook(self, cookbook: Cookbook) -> int:
        """Add a new cookbook"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        cursor.execute("""
            INSERT INTO cookbooks (name, authors, language, cuisine, config_path)
            VALUES (?, ?, ?, ?, ?)
        """, (
            cookbook.name,
            json.dumps(cookbook.authors) if isinstance(cookbook.authors, list) else cookbook.authors,
            cookbook.language,
            cookbook.cuisine,
            cookbook.config_path
        ))
        
        cookbook_id = cursor.lastrowid
        conn.commit()
        conn.close()
        
        return cookbook_id
    
    def get_cookbook(self, cookbook_id: int) -> Optional[Cookbook]:
        """Get cookbook by ID"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        cursor.execute("SELECT * FROM cookbooks WHERE id = ?", (cookbook_id,))
        row = cursor.fetchone()
        conn.close()
        
        if row:
            return Cookbook(**dict(row))
        return None
    
    def get_cookbook_by_name(self, name: str) -> Optional[Cookbook]:
        """Get cookbook by name"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        cursor.execute("SELECT * FROM cookbooks WHERE name = ?", (name,))
        row = cursor.fetchone()
        conn.close()
        
        if row:
            return Cookbook(**dict(row))
        return None
    
    def list_cookbooks(self) -> List[Cookbook]:
        """List all cookbooks"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        cursor.execute("SELECT * FROM cookbooks ORDER BY name")
        rows = cursor.fetchall()
        conn.close()
        
        return [Cookbook(**dict(row)) for row in rows]
    
    # ==================== Recipe Operations ====================
    
    def calculate_image_hash(self, image_path: str) -> str:
        """Calculate SHA256 hash of an image"""
        sha256 = hashlib.sha256()
        with open(image_path, 'rb') as f:
            for chunk in iter(lambda: f.read(4096), b""):
                sha256.update(chunk)
        return sha256.hexdigest()
    
    def is_duplicate(self, image_hash: str) -> Tuple[bool, Optional[int]]:
        """
        Check if image hash already exists
        Returns: (is_duplicate, recipe_id)
        """
        conn = self.get_connection()
        cursor = conn.cursor()
        
        cursor.execute(
            "SELECT id FROM recipes WHERE image_hash = ?",
            (image_hash,)
        )
        row = cursor.fetchone()
        conn.close()
        
        if row:
            return True, row['id']
        return False, None
    
    def add_recipe(self, recipe: Recipe) -> int:
        """Add a new recipe"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        cursor.execute("""
            INSERT INTO recipes (
                cookbook_id, title, page_number, image_hash, image_path,
                ingredients, instructions, background_info, handwritten_notes,
                prep_time, cook_time, total_time, servings, tags, cuisine,
                markdown_path, ocr_confidence
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            recipe.cookbook_id,
            recipe.title,
            recipe.page_number,
            recipe.image_hash,
            recipe.image_path,
            json.dumps(recipe.ingredients),
            json.dumps(recipe.instructions),
            recipe.background_info,
            recipe.handwritten_notes,
            recipe.prep_time,
            recipe.cook_time,
            recipe.total_time,
            recipe.servings,
            json.dumps(recipe.tags),
            recipe.cuisine,
            recipe.markdown_path,
            recipe.ocr_confidence
        ))
        
        recipe_id = cursor.lastrowid
        conn.commit()
        conn.close()
        
        return recipe_id
    
    def update_recipe(self, recipe: Recipe):
        """Update an existing recipe"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        cursor.execute("""
            UPDATE recipes SET
                cookbook_id = ?,
                title = ?,
                page_number = ?,
                image_path = ?,
                ingredients = ?,
                instructions = ?,
                background_info = ?,
                handwritten_notes = ?,
                prep_time = ?,
                cook_time = ?,
                total_time = ?,
                servings = ?,
                tags = ?,
                cuisine = ?,
                markdown_path = ?,
                ocr_confidence = ?
            WHERE id = ?
        """, (
            recipe.cookbook_id,
            recipe.title,
            recipe.page_number,
            recipe.image_path,
            json.dumps(recipe.ingredients),
            json.dumps(recipe.instructions),
            recipe.background_info,
            recipe.handwritten_notes,
            recipe.prep_time,
            recipe.cook_time,
            recipe.total_time,
            recipe.servings,
            json.dumps(recipe.tags),
            recipe.cuisine,
            recipe.markdown_path,
            recipe.ocr_confidence,
            recipe.id
        ))
        
        conn.commit()
        conn.close()

    def delete_recipe(self, recipe_id: int) -> bool:
        """
        Delete a recipe by ID
        Returns: True if successful, False otherwise
        """
        try:
            conn = self.get_connection()
            cursor = conn.cursor()

            cursor.execute("DELETE FROM recipes WHERE id = ?", (recipe_id,))

            conn.commit()
            deleted = cursor.rowcount > 0
            conn.close()

            return deleted
        except Exception as e:
            print(f"Error deleting recipe: {e}")
            return False

    def get_recipe(self, recipe_id: int) -> Optional[Recipe]:
        """Get recipe by ID"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        cursor.execute("SELECT * FROM recipes WHERE id = ?", (recipe_id,))
        row = cursor.fetchone()
        conn.close()
        
        if row:
            data = dict(row)
            # Parse JSON fields
            data['ingredients'] = json.loads(data['ingredients']) if data['ingredients'] else []
            data['instructions'] = json.loads(data['instructions']) if data['instructions'] else []
            data['tags'] = json.loads(data['tags']) if data['tags'] else []
            return Recipe(**data)
        return None
    
    def list_recipes(
        self,
        cookbook_id: Optional[int] = None,
        limit: Optional[int] = None
    ) -> List[Recipe]:
        """List recipes, optionally filtered by cookbook"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        if cookbook_id:
            query = "SELECT * FROM recipes WHERE cookbook_id = ? ORDER BY processed_at DESC"
            params = (cookbook_id,)
        else:
            query = "SELECT * FROM recipes ORDER BY processed_at DESC"
            params = ()
        
        if limit:
            query += f" LIMIT {limit}"
        
        cursor.execute(query, params)
        rows = cursor.fetchall()
        conn.close()
        
        recipes = []
        for row in rows:
            data = dict(row)
            data['ingredients'] = json.loads(data['ingredients']) if data['ingredients'] else []
            data['instructions'] = json.loads(data['instructions']) if data['instructions'] else []
            data['tags'] = json.loads(data['tags']) if data['tags'] else []
            recipes.append(Recipe(**data))
        
        return recipes
    
    def search_recipes(self, query: str) -> List[Recipe]:
        """Search recipes by title or tags"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT * FROM recipes 
            WHERE title LIKE ? OR tags LIKE ?
            ORDER BY processed_at DESC
        """, (f"%{query}%", f"%{query}%"))
        
        rows = cursor.fetchall()
        conn.close()
        
        recipes = []
        for row in rows:
            data = dict(row)
            data['ingredients'] = json.loads(data['ingredients']) if data['ingredients'] else []
            data['instructions'] = json.loads(data['instructions']) if data['instructions'] else []
            data['tags'] = json.loads(data['tags']) if data['tags'] else []
            recipes.append(Recipe(**data))
        
        return recipes
    
    # ==================== Mealie Sync Operations ====================
    
    def update_mealie_sync(self, recipe_id: int, mealie_id: str, content_hash: Optional[str] = None):
        """
        Update Mealie sync status.

        If content_hash is provided, it is stored so future bulk syncs can detect
        changes. If omitted, any existing hash is left untouched (backward-compatible).
        """
        conn = self.get_connection()
        cursor = conn.cursor()

        if content_hash is not None:
            cursor.execute("""
                UPDATE recipes
                SET mealie_id = ?, mealie_synced_at = CURRENT_TIMESTAMP, mealie_synced_hash = ?
                WHERE id = ?
            """, (mealie_id, content_hash, recipe_id))
        else:
            cursor.execute("""
                UPDATE recipes
                SET mealie_id = ?, mealie_synced_at = CURRENT_TIMESTAMP
                WHERE id = ?
            """, (mealie_id, recipe_id))

        conn.commit()
        conn.close()
    
    def clear_mealie_sync(self, recipe_id: int):
        """Reset a recipe's Mealie sync state (after it was deleted from Mealie)."""
        conn = self.get_connection()
        cursor = conn.cursor()

        cursor.execute("""
            UPDATE recipes
            SET mealie_id = NULL, mealie_synced_at = NULL, mealie_synced_hash = NULL
            WHERE id = ?
        """, (recipe_id,))

        conn.commit()
        conn.close()

    def get_unsynced_recipes(self) -> List[Recipe]:
        """Get recipes not yet synced to Mealie"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT * FROM recipes 
            WHERE mealie_id IS NULL
            ORDER BY processed_at DESC
        """)
        
        rows = cursor.fetchall()
        conn.close()
        
        recipes = []
        for row in rows:
            data = dict(row)
            data['ingredients'] = json.loads(data['ingredients']) if data['ingredients'] else []
            data['instructions'] = json.loads(data['instructions']) if data['instructions'] else []
            data['tags'] = json.loads(data['tags']) if data['tags'] else []
            recipes.append(Recipe(**data))
        
        return recipes
    
    # ==================== Processing Log Operations ====================
    
    def log_processing(
        self,
        image_path: str,
        image_hash: str,
        status: str,
        error_message: Optional[str] = None
    ):
        """Log processing attempt"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        cursor.execute("""
            INSERT INTO processing_log (image_path, image_hash, status, error_message)
            VALUES (?, ?, ?, ?)
        """, (image_path, image_hash, status, error_message))
        
        conn.commit()
        conn.close()
    
    def get_processing_stats(self) -> Dict:
        """Get processing statistics"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        # Total recipes
        cursor.execute("SELECT COUNT(*) as count FROM recipes")
        total_recipes = cursor.fetchone()['count']
        
        # By status
        cursor.execute("""
            SELECT status, COUNT(*) as count 
            FROM processing_log 
            GROUP BY status
        """)
        status_counts = {row['status']: row['count'] for row in cursor.fetchall()}
        
        # Mealie sync stats
        cursor.execute("""
            SELECT 
                COUNT(*) as total,
                SUM(CASE WHEN mealie_id IS NOT NULL THEN 1 ELSE 0 END) as synced
            FROM recipes
        """)
        sync_stats = dict(cursor.fetchone())
        
        # By cookbook
        cursor.execute("""
            SELECT c.name, COUNT(r.id) as count
            FROM cookbooks c
            LEFT JOIN recipes r ON c.id = r.cookbook_id
            GROUP BY c.id
        """)
        cookbook_counts = {row['name']: row['count'] for row in cursor.fetchall()}
        
        conn.close()
        
        return {
            'total_recipes': total_recipes,
            'processing_status': status_counts,
            'mealie_sync': sync_stats,
            'by_cookbook': cookbook_counts
        }

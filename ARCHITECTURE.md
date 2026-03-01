# Recipe Digitization System - Architecture

## 🎯 System Overview

A complete recipe digitization pipeline with:
- **Automatic processing** with duplicate detection
- **Local SQLite database** for tracking and storage
- **Mealie integration** for recipe management
- **User-friendly GUI** for non-technical users
- **Organized output** with markdown exports
- **Per-cookbook configuration** for optimal extraction

---

## 📐 System Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                     USER INTERFACE                          │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐     │
│  │  GUI Client  │  │   CLI Tool   │  │ Folder Watch │     │
│  │  (Electron)  │  │   (Python)   │  │   (Daemon)   │     │
│  └──────┬───────┘  └──────┬───────┘  └──────┬───────┘     │
└─────────┼──────────────────┼──────────────────┼────────────┘
          │                  │                  │
          └──────────────────┴──────────────────┘
                             ▼
┌─────────────────────────────────────────────────────────────┐
│                   CORE PROCESSING ENGINE                     │
│  ┌──────────────────────────────────────────────────────┐  │
│  │  Recipe Processor                                     │  │
│  │  • Image hash checking (deduplication)               │  │
│  │  • Apple OCR extraction                              │  │
│  │  • OpenAI parsing with config hints                  │  │
│  │  • Database storage                                  │  │
│  │  • Markdown export                                   │  │
│  │  • Mealie sync                                       │  │
│  └──────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────┘
                             ▼
┌─────────────────────────────────────────────────────────────┐
│                      DATA LAYER                              │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐     │
│  │   SQLite DB  │  │   Markdown   │  │    Mealie    │     │
│  │   (Local)    │  │   (Export)   │  │     (API)    │     │
│  └──────────────┘  └──────────────┘  └──────────────┘     │
└─────────────────────────────────────────────────────────────┘
```

---

## 📂 Directory Structure

```
~/recipe-manager/
├── app/
│   ├── recipe_processor.py      # Core processing engine
│   ├── database.py              # SQLite database manager
│   ├── mealie_client.py         # Mealie API integration
│   ├── config_manager.py        # Config file handling
│   ├── apple_ocr.swift          # Apple Vision OCR
│   └── utils.py                 # Helper functions
├── cli/
│   ├── recipe_cli.py            # CLI interface
│   └── folder_watcher.py        # Automatic folder monitoring
├── gui/
│   ├── app.py                   # GUI application (Streamlit)
│   └── assets/                  # GUI assets
├── data/
│   ├── recipes.db               # SQLite database
│   └── cache/                   # Temporary processing cache
├── cookbooks/
│   ├── jerusalem/
│   │   ├── config.json          # Cookbook config
│   │   ├── images/              # Raw images
│   │   │   ├── page001.jpg
│   │   │   └── page002.jpg
│   │   └── extracted/           # Markdown exports
│   │       ├── Roasted_Chicken.md
│   │       └── Hummus.md
│   ├── ottolenghi_simple/
│   │   ├── config.json
│   │   ├── images/
│   │   └── extracted/
│   └── family_recipes/
│       ├── config.json
│       ├── images/
│       └── extracted/
├── config/
│   ├── settings.yaml            # Global settings
│   └── mealie_config.json       # Mealie connection info
├── requirements.txt
├── README.md
└── setup.sh
```

---

## 🗄️ Database Schema

```sql
-- Cookbooks table
CREATE TABLE cookbooks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    authors TEXT,
    language TEXT DEFAULT 'en',
    cuisine TEXT,
    config_path TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Recipes table
CREATE TABLE recipes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    cookbook_id INTEGER,
    title TEXT NOT NULL,
    page_number INTEGER,
    image_hash TEXT UNIQUE,          -- SHA256 of image (deduplication)
    image_path TEXT,
    
    -- Recipe content
    ingredients TEXT,                 -- JSON array
    instructions TEXT,                -- JSON array
    background_info TEXT,
    handwritten_notes TEXT,
    
    -- Metadata
    prep_time TEXT,
    cook_time TEXT,
    total_time TEXT,
    servings TEXT,
    tags TEXT,                        -- JSON array
    cuisine TEXT,
    
    -- Tracking
    processed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    markdown_path TEXT,
    mealie_id TEXT,                   -- Mealie recipe ID
    mealie_synced_at TIMESTAMP,
    
    -- Quality metrics
    ocr_confidence REAL,
    
    FOREIGN KEY (cookbook_id) REFERENCES cookbooks(id)
);

-- Processing log
CREATE TABLE processing_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    image_path TEXT,
    image_hash TEXT,
    status TEXT,                      -- 'success', 'failed', 'duplicate', 'skipped'
    error_message TEXT,
    processed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Indexes for performance
CREATE INDEX idx_recipes_cookbook ON recipes(cookbook_id);
CREATE INDEX idx_recipes_image_hash ON recipes(image_hash);
CREATE INDEX idx_recipes_mealie_id ON recipes(mealie_id);
CREATE INDEX idx_processing_log_hash ON processing_log(image_hash);
```

---

## ⚙️ Configuration Files

### Global Settings (`config/settings.yaml`)

```yaml
# Global application settings

# Directories
cookbooks_dir: "~/recipe-manager/cookbooks"
database_path: "~/recipe-manager/data/recipes.db"
output_format: "markdown"  # or "json"

# Processing
auto_process_new_images: true
skip_duplicates: true
confidence_threshold: 0.7

# OCR
ocr_language: "en"

# OpenAI
openai_model: "gpt-4o"
openai_max_tokens: 2000
openai_temperature: 0.1

# Mealie
mealie_enabled: true
mealie_base_url: "http://localhost:9000"
mealie_auto_sync: true

# Folder watching
watch_folders: true
watch_interval: 30  # seconds
```

### Cookbook Config (`cookbooks/jerusalem/config.json`)

```json
{
  "cookbook": {
    "name": "Jerusalem",
    "authors": ["Yotam Ottolenghi", "Sami Tamimi"],
    "language": "en",
    "cuisine": "Middle Eastern",
    "publisher": "Ten Speed Press",
    "year": 2012
  },
  
  "layout": {
    "has_background_stories": true,
    "background_location": "top-of-page",
    "ingredients_side": "left-column",
    "instructions_side": "right-column",
    "typical_columns": 2,
    "font_style": "modern-serif",
    "common_elements": ["ingredient-header", "method-header", "author-notes"]
  },
  
  "extraction_hints": {
    "description": "Ottolenghi's Jerusalem cookbook typically features background stories at the top of each page, often in italics or smaller font. These should be separated from the actual cooking instructions.",
    "special_instructions": "Watch for handwritten notes in margins. Ingredient quantities often use metric measurements.",
    "common_headings": {
      "ingredients": ["Ingredients", "For the", "You will need"],
      "instructions": ["Method", "To make", "Instructions"],
      "notes": ["Note", "Tip", "Variation"]
    }
  },
  
  "default_tags": ["middle-eastern", "jerusalem", "ottolenghi", "mediterranean"],
  
  "image_settings": {
    "typical_orientation": "portrait",
    "recipes_per_page": 1,
    "has_photos": true
  }
}
```

### Mealie Config (`config/mealie_config.json`)

```json
{
  "base_url": "http://localhost:9000",
  "api_token": "your-mealie-api-token",
  "default_group": "My Recipes",
  "tag_prefix": "imported",
  "auto_categories": true,
  "import_images": true
}
```

---

## 🔄 Processing Workflow

### 1. Image Ingestion
```
User adds image → Calculate SHA256 hash → Check database for duplicate
                    ↓ (if new)
                Store in processing queue
```

### 2. OCR Extraction
```
Image → Apple Vision OCR → Extract text with confidence score
                          → Store in cache
```

### 3. AI Parsing
```
OCR text + Image + Config → OpenAI GPT-4o → Structured recipe data
                                          → Validate fields
```

### 4. Storage
```
Recipe data → Save to SQLite database
           → Export to markdown
           → Update processing log
```

### 5. Mealie Sync (Optional)
```
Recipe data → Format for Mealie API
           → POST to Mealie
           → Store Mealie recipe ID
           → Update sync timestamp
```

---

## 🖥️ User Interfaces

### CLI Interface
```bash
# Process single image
recipe-cli process image.jpg --cookbook jerusalem

# Process entire cookbook
recipe-cli process-folder ~/cookbooks/jerusalem/images/

# Sync to Mealie
recipe-cli sync --cookbook jerusalem

# Check database
recipe-cli stats
recipe-cli list --cookbook jerusalem

# Create new cookbook
recipe-cli init-cookbook --name "Family Recipes"
```

### GUI Interface (Streamlit)
- Drag & drop images
- Select cookbook from dropdown
- View processing status in real-time
- Preview extracted recipes
- Edit before saving
- One-click Mealie sync
- Browse recipe database
- Search and filter

### Folder Watcher (Background Daemon)
- Monitors cookbook folders
- Auto-processes new images
- Sends desktop notifications
- Logs all activity

---

## 🔌 Mealie Integration

### API Operations

**1. Authentication**
```python
headers = {
    "Authorization": f"Bearer {api_token}",
    "Content-Type": "application/json"
}
```

**2. Create Recipe**
```python
POST /api/recipes
{
    "name": "Roasted Chicken with Sumac",
    "description": "Traditional Middle Eastern roasted chicken",
    "recipeIngredient": ["1 whole chicken", "3 tbsp sumac", ...],
    "recipeInstructions": [
        {"text": "Preheat oven to 200°C"},
        {"text": "Mix sumac with olive oil"},
        ...
    ],
    "prepTime": "PT15M",
    "cookTime": "PT1H",
    "totalTime": "PT1H15M",
    "recipeYield": "4 servings",
    "tags": ["middle-eastern", "chicken", "ottolenghi"]
}
```

**3. Upload Image**
```python
POST /api/recipes/{recipe_id}/image
Content-Type: multipart/form-data
```

**4. Get Recipe**
```python
GET /api/recipes/{recipe_id}
```

---

## 🎨 GUI Mockup

```
┌────────────────────────────────────────────────────────────┐
│  Recipe Digitizer                                    [_][□][X] │
├────────────────────────────────────────────────────────────┤
│                                                              │
│  📚 Select Cookbook: [Jerusalem ▼]  [+ New Cookbook]       │
│                                                              │
│  ┌────────────────────────────────────────────────────┐   │
│  │                                                      │   │
│  │      Drag & Drop Images Here                        │   │
│  │                                                      │   │
│  │      or click to browse                             │   │
│  │                                                      │   │
│  └────────────────────────────────────────────────────┘   │
│                                                              │
│  Processing Queue:                                          │
│  ┌────────────────────────────────────────────────────┐   │
│  │ ✓ page001.jpg  →  Roasted Chicken     [View] [Edit] │   │
│  │ ⏳ page002.jpg  →  Processing...                    │   │
│  │ ✓ page003.jpg  →  Hummus               [View] [Edit] │   │
│  └────────────────────────────────────────────────────┘   │
│                                                              │
│  [Process All]  [Sync to Mealie]  [View Database]          │
│                                                              │
│  Status: 2/3 recipes processed | 1 synced to Mealie         │
└────────────────────────────────────────────────────────────┘
```

---

## 🚀 Implementation Phases

### Phase 1: Core Engine (Week 1)
- ✅ Apple OCR + OpenAI extraction (DONE)
- Database schema & manager
- Config file handling
- Deduplication logic
- Markdown export

### Phase 2: Mealie Integration (Week 1)
- Mealie API client
- Recipe format conversion
- Image upload
- Sync status tracking

### Phase 3: CLI Interface (Week 2)
- Command-line tool
- Batch processing
- Progress bars
- Error handling
- Statistics reporting

### Phase 4: GUI Application (Week 2-3)
- Streamlit interface
- Drag & drop
- Real-time processing
- Recipe editor
- Database browser

### Phase 5: Automation (Week 3)
- Folder watcher daemon
- Desktop notifications
- Scheduled syncing
- Error recovery

### Phase 6: Polish (Week 4)
- Comprehensive testing
- Documentation
- Installation wizard
- User guide
- Video tutorial

---

## 📊 Key Features

### Deduplication
- SHA256 hash of each image
- Check before processing
- Prevents duplicate entries
- Logs skipped duplicates

### Smart Processing
- Config-aware extraction
- Language detection
- Layout analysis
- Quality scoring

### Robust Error Handling
- Failed processing logged
- Retry mechanism
- Manual review queue
- Error notifications

### Performance
- Async processing
- Batch operations
- Database indexing
- Cached OCR results

### User Experience
- Progress indicators
- Desktop notifications
- Undo/redo support
- Recipe preview
- Search & filter

---

## 🔐 Security & Privacy

- API keys stored in secure keychain (macOS)
- Local-first architecture
- Optional Mealie self-hosting
- No cloud processing of images (OCR local, AI via API)
- Database encryption option

---

## 📈 Future Enhancements

- Multi-language support
- Recipe recommendations based on ingredients
- Meal planning integration
- Shopping list generation
- Nutritional information extraction
- Recipe scaling
- Ingredient substitution suggestions
- Mobile app for photo capture
- Cloud backup option
- Recipe sharing community

---

This architecture provides a solid foundation for a production-ready recipe digitization system!

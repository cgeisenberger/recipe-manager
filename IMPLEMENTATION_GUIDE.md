# Complete Implementation Guide

## 🎯 System Components

You now have a complete recipe digitization system with:

✅ **Apple OCR + OpenAI parsing** (working!)  
✅ **SQLite database** with deduplication  
✅ **Mealie integration** for recipe management  
✅ **CLI tool** for easy operation  
✅ **Markdown export** with organized folders  
✅ **Per-cookbook configuration** support  

---

## 📁 Project Structure

```
~/recipe-manager/
├── app/
│   ├── apple_ocr.swift              # Apple Vision OCR
│   ├── recipe_processor_integrated.py  # Core processor
│   ├── database.py                  # Database manager
│   ├── mealie_client.py             # Mealie API client
│   └── recipe_cli.py                # CLI interface
├── data/
│   └── recipes.db                   # SQLite database
├── cookbooks/
│   ├── jerusalem/
│   │   ├── config.json
│   │   ├── images/
│   │   │   ├── page001.jpg
│   │   │   └── page002.jpg
│   │   └── extracted/
│   │       ├── Roasted_Chicken.md
│   │       └── Hummus.md
│   └── ottolenghi_simple/
│       ├── config.json
│       ├── images/
│       └── extracted/
├── config/
│   └── mealie_config.json           # Optional Mealie config
├── requirements.txt
└── README.md
```

---

## 🚀 Quick Start

### Step 1: Install Dependencies

```bash
conda activate recipes  # or your venv
pip install -r requirements.txt
```

### Step 2: Set Environment Variables

```bash
# Required
export OPENAI_API_KEY='sk-your-key-here'

# Optional (for Mealie)
export MEALIE_URL='http://localhost:9000'
export MEALIE_TOKEN='your-mealie-token'
```

Add to `~/.zshrc` for persistence:
```bash
echo 'export OPENAI_API_KEY="sk-..."' >> ~/.zshrc
echo 'export MEALIE_URL="http://localhost:9000"' >> ~/.zshrc
echo 'export MEALIE_TOKEN="your-token"' >> ~/.zshrc
source ~/.zshrc
```

### Step 3: Test the System

```bash
# Process a single image
python recipe_cli.py process test_image.jpg --cookbook "Test"

# View database stats
python recipe_cli.py stats
```

---

## 📚 CLI Commands

### Process Recipes

```bash
# Single image
python recipe_cli.py process image.jpg --cookbook "Jerusalem"

# Entire folder
python recipe_cli.py process cookbooks/jerusalem/images/

# With Mealie sync
python recipe_cli.py process cookbooks/jerusalem/images/ --sync-mealie

# Don't skip duplicates
python recipe_cli.py process image.jpg --cookbook "Jerusalem" --no-skip-duplicates
```

### Database Operations

```bash
# Show statistics
python recipe_cli.py stats

# List all recipes
python recipe_cli.py list

# List recipes from specific cookbook
python recipe_cli.py list --cookbook "Jerusalem"

# List last 10 recipes
python recipe_cli.py list --limit 10

# Search recipes
python recipe_cli.py search "chicken"
python recipe_cli.py search "sumac"
```

### Mealie Sync

```bash
# Sync all unsynced recipes
python recipe_cli.py sync --all

# Sync specific cookbook
python recipe_cli.py sync --cookbook "Jerusalem"

# With explicit credentials
python recipe_cli.py sync --all \
  --mealie-url http://localhost:9000 \
  --mealie-token your-token
```

### Initialize New Cookbook

```bash
# Create cookbook structure
python recipe_cli.py init-cookbook "Family Recipes" \
  --authors "Mom, Grandma" \
  --language en \
  --cuisine "American"

# This creates:
# cookbooks/Family_Recipes/
#   ├── config.json
#   ├── images/
#   └── extracted/
```

---

## ⚙️ Configuration

### Global Settings

Create `config/settings.yaml` (optional):

```yaml
database_path: "data/recipes.db"
output_format: "markdown"
skip_duplicates: true
confidence_threshold: 0.7

openai_model: "gpt-4o"
openai_temperature: 0.1

mealie_enabled: true
mealie_auto_sync: false
```

### Cookbook Configuration

Each cookbook should have a `config.json`:

```json
{
  "cookbook": {
    "name": "Jerusalem",
    "authors": ["Yotam Ottolenghi", "Sami Tamimi"],
    "language": "en",
    "cuisine": "Middle Eastern"
  },
  
  "layout": {
    "has_background_stories": true,
    "background_location": "top-of-page",
    "ingredients_side": "left-column",
    "instructions_side": "right-column",
    "typical_columns": 2
  },
  
  "extraction_instructions": "Background stories at top in italics, separate from cooking steps",
  
  "default_tags": ["middle-eastern", "ottolenghi"]
}
```

### Mealie Configuration

Create `config/mealie_config.json`:

```json
{
  "base_url": "http://localhost:9000",
  "api_token": "your-mealie-api-token",
  "auto_sync": false,
  "import_images": true
}
```

---

## 🔄 Typical Workflows

### Workflow 1: Digitize a New Cookbook

```bash
# 1. Create cookbook structure
python recipe_cli.py init-cookbook "My New Cookbook" \
  --authors "Author Name" \
  --cuisine "Italian"

# 2. Edit config
nano cookbooks/My_New_Cookbook/config.json

# 3. Add photos to images folder
cp ~/Photos/recipes/*.jpg cookbooks/My_New_Cookbook/images/

# 4. Process all images
python recipe_cli.py process cookbooks/My_New_Cookbook/images/

# 5. Check results
python recipe_cli.py list --cookbook "My New Cookbook"

# 6. Sync to Mealie
python recipe_cli.py sync --cookbook "My New Cookbook"
```

### Workflow 2: Process Single Recipe

```bash
# Take photo with phone → AirDrop to Mac
# Save to: cookbooks/jerusalem/images/new_recipe.jpg

# Process it
python recipe_cli.py process \
  cookbooks/jerusalem/images/new_recipe.jpg \
  --sync-mealie

# View result
cat cookbooks/jerusalem/extracted/Recipe_Name.md
```

### Workflow 3: Batch Process & Review

```bash
# Process folder (skip duplicates)
python recipe_cli.py process cookbooks/jerusalem/images/

# Review database
python recipe_cli.py stats
python recipe_cli.py list --cookbook "Jerusalem"

# Search for specific recipe
python recipe_cli.py search "chicken"

# Sync selected cookbook
python recipe_cli.py sync --cookbook "Jerusalem"
```

---

## 🗄️ Database Schema

The SQLite database tracks:

**Cookbooks Table:**
- ID, name, authors, language, cuisine
- Config file path
- Creation timestamp

**Recipes Table:**
- ID, cookbook reference
- Title, page number
- Image hash (SHA256 - for deduplication)
- Image path
- Recipe content (ingredients, instructions, notes)
- Metadata (times, servings, tags)
- Markdown export path
- Mealie sync status (ID, timestamp)
- OCR confidence score

**Processing Log:**
- Image path, hash
- Status (success, failed, duplicate, skipped)
- Error messages
- Timestamp

---

## 🔍 Duplicate Detection

The system automatically prevents duplicate processing:

1. **Image Hash**: SHA256 calculated for each image
2. **Database Check**: Hash checked before processing
3. **Skip or Process**: 
   - By default: Skip duplicates
   - With `--no-skip-duplicates`: Process anyway
4. **Logging**: All attempts logged in processing_log table

Example:
```bash
# First time: Processes
python recipe_cli.py process image.jpg --cookbook "Test"
# Output: ✓ Processed

# Second time: Skips
python recipe_cli.py process image.jpg --cookbook "Test"
# Output: ⏭️  Skipped (duplicate - recipe #123)

# Force reprocess
python recipe_cli.py process image.jpg --cookbook "Test" --no-skip-duplicates
# Output: ✓ Processed (new recipe ID)
```

---

## ☁️ Mealie Integration

### Setup Mealie

**Option 1: Docker (Easiest)**
```bash
docker run -d \
  --name mealie \
  -p 9000:9000 \
  -v mealie-data:/app/data \
  ghcr.io/mealie-recipes/mealie:latest
```

**Option 2: Self-hosted**  
Follow: https://docs.mealie.io/documentation/getting-started/installation/

### Get API Token

1. Open Mealie: http://localhost:9000
2. Create account & login
3. Go to: Profile → API Tokens
4. Generate new token
5. Copy token

### Configure

```bash
export MEALIE_URL="http://localhost:9000"
export MEALIE_TOKEN="your-token-here"
```

### Sync Recipes

```bash
# Test connection
python recipe_cli.py sync --cookbook "Jerusalem"

# Sync all unsynced
python recipe_cli.py sync --all
```

---

## 📊 Monitoring & Stats

```bash
# Overall statistics
python recipe_cli.py stats

# Output:
# 📊 Recipe Database Statistics
# 
# Total Recipes: 47
# 
# Processing Status:
#   success: 45
#   duplicate: 8
#   failed: 2
# 
# Mealie Sync:
#   Total: 47
#   Synced: 40
#   Unsynced: 7
# 
# By Cookbook:
#   Jerusalem: 25
#   Ottolenghi Simple: 15
#   Family Recipes: 7
```

---

## 🐛 Troubleshooting

### "No module named 'database'"

Make sure all files are in the same directory:
```bash
ls -la
# Should see: apple_ocr.swift, database.py, mealie_client.py, 
#             recipe_processor_integrated.py, recipe_cli.py
```

### "OCR failed"

Check Swift script:
```bash
swift apple_ocr.swift test_image.jpg
```

### "OpenAI API error"

Check API key:
```bash
echo $OPENAI_API_KEY
```

### "Mealie connection failed"

Test Mealie:
```bash
curl http://localhost:9000/api/app/about
```

### Database locked

Close other connections:
```bash
lsof data/recipes.db
# Kill any processes using it
```

---

## 💡 Pro Tips

1. **Config Files Matter**: Spend 5 minutes on a good config - saves hours of corrections

2. **Batch Processing**: Process entire cookbooks at once for consistency

3. **Review Before Mealie**: Check markdown exports before syncing to Mealie

4. **Backup Database**: 
   ```bash
   cp data/recipes.db data/recipes.db.backup
   ```

5. **Search is Powerful**: 
   ```bash
   python recipe_cli.py search "vegetarian"
   python recipe_cli.py search "quick"
   ```

6. **Use Tags Consistently**: Add cookbook-specific tags in config

7. **Monitor Confidence**: Low OCR confidence (<0.7) may need review

---

## 📈 Next Steps

1. **Set up Mealie** for full recipe management
2. **Process your first cookbook** end-to-end
3. **Create a GUI** using Streamlit (coming soon)
4. **Add folder watching** for automatic processing
5. **Export to other formats** (PDF, web, etc.)

---

## 🎉 You're Ready!

The system is complete and ready to use. Start with:

```bash
# Create your first cookbook
python recipe_cli.py init-cookbook "My Favorites"

# Add some images
# cookbooks/My_Favorites/images/

# Process them
python recipe_cli.py process cookbooks/My_Favorites/images/

# View results
python recipe_cli.py list
```

Happy cooking! 👨‍🍳

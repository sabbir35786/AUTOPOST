import os
import sys
from dotenv import load_dotenv

sys.path.insert(0, os.path.abspath("."))
load_dotenv()

from app.mistral_service import generate_persona_from_posts

print("Testing persona generation...")
result = generate_persona_from_posts(["This is a test post that I wrote about being super happy! 🚀"])
print("Result:", result)

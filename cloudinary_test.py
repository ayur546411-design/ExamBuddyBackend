import os
import cloudinary
import cloudinary.api
from dotenv import load_dotenv

load_dotenv()

cloudinary.config(
  cloud_name = os.getenv('CLOUDINARY_CLOUD_NAME'),
  api_key = os.getenv('CLOUDINARY_API_KEY'),
  api_secret = os.getenv('CLOUDINARY_API_SECRET'),
  secure = True
)

def list_pdfs():
    res = cloudinary.api.resources(resource_type='raw', max_results=50)
    for resource in res.get('resources', []):
        if resource['public_id'].endswith('.pdf'):
            print(f"URL: {resource['url']}")
            print(f"Public ID: {resource['public_id']}")
            print(f"Folder: {resource.get('folder')}")
            print("-" * 50)

if __name__ == "__main__":
    list_pdfs()

import os
import httpx
import asyncio
from pathlib.Path import Path

# IMPORTANT: Ensure your FastAPI server is running before executing this script!
API_URL = "http://localhost:8000/api/v1/documents/upload"

async def upload_pdf(file_path: str, document_type: str, subject_id: str = None, department_id: str = None):
    print(f"Uploading {file_path}...")
    
    with open(file_path, "rb") as f:
        files = {"file": (os.path.basename(file_path), f, "application/pdf")}
        data = {
            "document_type": document_type
        }
        if subject_id:
            data["subject_id"] = subject_id
        if department_id:
            data["department_id"] = department_id
            
        async with httpx.AsyncClient(timeout=120.0) as client:
            try:
                response = await client.post(API_URL, files=files, data=data)
                if response.status_code == 200:
                    print(f"✅ Success: {response.json().get('message')}")
                    print(f"🔗 Cloudinary URL: {response.json().get('cloudinary_url')}")
                else:
                    print(f"❌ Error {response.status_code}: {response.text}")
            except Exception as e:
                print(f"❌ Request failed: {e}")

async def main():
    print("=== GGU Prep Bulk PDF Uploader ===")
    print("Make sure your FastAPI server is running!")
    
    # Example usage:
    # 1. Put your PDFs in a folder called 'pdfs' next to this script
    # 2. Get the Subject ID or Department ID from your Supabase database
    # 3. Call the upload function
    
    # --- Example: Uploading all PYQs in a directory ---
    # subject_id_from_db = "INSERT-UUID-HERE" 
    # pdf_directory = "./pdfs"
    # 
    # if os.path.exists(pdf_directory):
    #     for filename in os.listdir(pdf_directory):
    #         if filename.endswith(".pdf"):
    #             file_path = os.path.join(pdf_directory, filename)
    #             await upload_pdf(file_path, "pyq", subject_id=subject_id_from_db)
    # else:
    #     print(f"Directory {pdf_directory} not found. Create it and put PDFs inside.")
    
    print("Script finished. Edit this file to add your logic.")

if __name__ == "__main__":
    asyncio.run(main())

import asyncio
from app.db.session import AsyncSessionLocal
from sqlalchemy import select, func
from app.models.document import Document

async def main():
    async with AsyncSessionLocal() as db:
        # Group by cloudinary_url to see how many subjects were extracted per PDF
        results = (await db.execute(
            select(Document.cloudinary_url, Document.title, func.length(Document.extracted_text), func.count(Document.id))
            .where(Document.document_type == 'syllabus')
            .group_by(Document.cloudinary_url, Document.title, Document.extracted_text)
        )).all()
        
        # Group by url, sum counts to get total subjects per PDF
        pdf_stats = {}
        for url, title, text_len, count in results:
            if url not in pdf_stats:
                pdf_stats[url] = {"len": text_len, "count": 0, "titles": []}
            pdf_stats[url]["count"] += count
            pdf_stats[url]["titles"].append(title)
            
        print(f"Found {len(pdf_stats)} unique Syllabus PDFs")
        for url, stats in list(pdf_stats.items())[:5]:
            print(f"PDF length: {stats['len']} chars | Extracted Subjects: {stats['count']}")
            print(f"Subjects: {', '.join(stats['titles'][:5])}...")
            print("-" * 50)

if __name__ == "__main__":
    asyncio.run(main())

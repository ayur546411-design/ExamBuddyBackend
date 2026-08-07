"""
test_extraction.py — Quick end-to-end extraction test with new SDK
"""
import asyncio
import sys
import os

# Load env
with open(".env") as f:
    for line in f:
        if "=" in line:
            k, v = line.strip().split("=", 1)
            os.environ[k] = v

async def main():
    from app.services.gemini_service import extract_structured_data_from_pdf_text
    
    print("Testing extraction with confirmed working models...")
    print("=" * 55)
    
    test_text = """
--- PAGE 1 ---
GGU B.Tech Information Technology — Semester III Syllabus

Subject Code: IT301
Subject Name: DATA STRUCTURES AND ALGORITHMS
Credits: 4 (3L + 1T)

UNIT 1: Introduction to Data Structures
Topics: Arrays, Linked Lists, Stacks, Queues, Complexity analysis

UNIT 2: Trees and Graphs
Topics: Binary Trees, BST, AVL Trees, Graph BFS, DFS

Learning Outcomes:
1. Understand fundamental data structures
2. Analyze algorithm complexity

Reference Books:
1. Cormen, Introduction to Algorithms, MIT Press

--- PAGE 2 ---
Subject Code: IT302
Subject Name: COMPUTER NETWORKS
Credits: 3

UNIT 1: Introduction to Networks
Topics: OSI Model, TCP/IP, Network Topologies

UNIT 2: Data Link Layer
Topics: Error Detection, Flow Control, MAC protocols
"""
    
    result = await extract_structured_data_from_pdf_text(test_text, "syllabus")
    
    subjects = result.get("Subjects", [])
    print(f"\nResult: {len(subjects)} subjects extracted")
    
    for i, s in enumerate(subjects):
        print(f"\n  Subject {i+1}: {s.get('Subject Name')}")
        print(f"    Code: {s.get('Subject Code')}")
        print(f"    Credits: {s.get('Credits')}")
        units = s.get('Units', [])
        print(f"    Units: {len(units)}")
        for u in units:
            topics = u.get('Topics', [])
            print(f"      - {u.get('Unit Name')} ({len(topics)} topics)")
    
    if len(subjects) >= 2:
        print("\n[PASS] Extracted multiple subjects correctly")
    elif len(subjects) == 1:
        print("\n[PARTIAL] Only 1 subject extracted (expected 2)")
    else:
        print(f"\n[FAIL] No subjects extracted. Result: {result}")

asyncio.run(main())

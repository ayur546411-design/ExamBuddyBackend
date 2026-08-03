import requests
import json

API_URL = 'https://projectb-p0tv.onrender.com/api/v1'

def test_prod_api():
    # 1. Onboard user to get token
    payload = {
        'full_name': 'Test Debugger',
        'school_id': 'f958e9f1-92fa-48b3-a0d3-c9b1c4b7063e',
        'department_id': '0e3dd991-3391-405e-aa8b-9510f4f10f8f',
        'role': 'student'
    }
    print(f'Creating user at {API_URL}/auth/onboard')
    res = requests.post(f'{API_URL}/auth/onboard', json=payload)
    if res.status_code != 201:
        print(f'Failed to register: {res.text}')
        return
        
    token = res.json().get('access_token')
    print(f'Token: {token[:20]}...')
    
    headers = {'Authorization': f'Bearer {token}'}
    
    # 2. Get Semesters
    print(f'\nFetching semesters...')
    res = requests.get(f'{API_URL}/semesters/', headers=headers)
    if res.status_code != 200:
        print(f'Error fetching semesters: {res.text}')
        return
    sems = res.json()
    print(f'Semesters returned: {len(sems)}')
    for s in sems:
        print(f" - {s.get('semester_number')} (ID: {s.get('id')})")
        
    if not sems:
        print('No semesters found!')
        return
        
    sem_id = sems[0].get('id')
    
    # 3. Get Subjects
    print(f'\nFetching subjects for semester {sem_id}...')
    res = requests.get(f'{API_URL}/subjects/?semester_id={sem_id}', headers=headers)
    if res.status_code != 200:
        print(f'Error fetching subjects: {res.text}')
        return
    subs = res.json()
    print(f'Subjects returned: {len(subs)}')
    for s in subs:
        print(f" - {s.get('name')} (ID: {s.get('id')})")
        
    if not subs:
        print('No subjects found!')
        return
        
    sub_id = subs[0].get('id')
    
    # 4. Get Documents (Syllabus)
    print(f'\nFetching Syllabus for subject {sub_id}...')
    res = requests.get(f'{API_URL}/documents/?subject_id={sub_id}&document_type=syllabus', headers=headers)
    if res.status_code != 200:
        print(f'Error fetching documents: {res.text}')
        return
    docs = res.json()
    print(f'Syllabus Documents returned: {len(docs)}')
    for d in docs:
        print(f" - {d.get('title')} (URL: {d.get('cloudinary_url')})")

if __name__ == '__main__':
    test_prod_api()

import requests
url = "http://127.0.0.1:8000/api/v1/documents/upload"
files = {'file': ('dummy.pdf', b'dummy content', 'application/pdf')}
data = {'document_type': 'academic_calendar'}
r = requests.post(url, files=files, data=data)
print(r.status_code)
print(r.text)

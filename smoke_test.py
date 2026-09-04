import os
os.environ.setdefault("UPLOAD_PASSWORD", "testpass123")
os.environ.setdefault("SECRET_KEY", "test-secret")

from app import app

client = app.test_client()

def check(name, resp, expect_status):
    status = resp.status_code
    ok = status == expect_status
    print(f"{'OK  ' if ok else 'FAIL'} {name}: got {status}, expected {expect_status}")
    return ok

results = []
results.append(check("GET /", client.get("/"), 200))
results.append(check("GET /login", client.get("/login"), 200))

r = client.post("/login", data={"password": "wrong"}, follow_redirects=False)
results.append(check("POST /login wrong password", r, 200))

results.append(check("GET /upload (not logged in) redirects", client.get("/upload"), 302))

r = client.post("/login", data={"password": "testpass123"}, follow_redirects=False)
results.append(check("POST /login correct password redirects", r, 302))

# use a session-persisting client for the authed checks
with app.test_client() as c:
    c.post("/login", data={"password": "testpass123"})
    results.append(check("GET /upload (logged in)", c.get("/upload"), 200))

results.append(check("GET /album/nonexistent (no cloudinary configured)", client.get("/album/nonexistent"), 404))

print()
if all(results):
    print("ALL CHECKS PASSED")
else:
    print("SOME CHECKS FAILED")
    raise SystemExit(1)

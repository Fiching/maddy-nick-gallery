"""Verifies the public/private split: anyone can view albums, browse
photos, and download them without logging in, but every change (upload,
rename, delete, reorder, set cover) still requires the shared password --
and the page itself doesn't even show those controls to a logged-out
visitor."""
import os
os.environ.setdefault("UPLOAD_PASSWORD", "testpass123")
os.environ.setdefault("SECRET_KEY", "test-secret")

import app as appmod

appmod.CLOUDINARY_CONFIGURED = True
appmod.cloudinary.config(cloud_name="test-cloud", api_key="x", api_secret="y", secure=True)

STORE = {}
_counter = {"n": 0}

def _next_ts():
    _counter["n"] += 1
    return f"2026-09-11T00:00:{_counter['n']:02d}Z"

def seed(slug, filenames):
    for name in filenames:
        pid = f"albums/{slug}/{name}"
        STORE[pid] = {"context": {}, "created_at": _next_ts()}

def fake_resources(type=None, prefix=None, max_results=None, context=None):
    items = [
        {"public_id": pid, "created_at": data["created_at"], "context": {}}
        for pid, data in STORE.items()
        if prefix is None or pid.startswith(prefix)
    ]
    items.sort(key=lambda r: r["created_at"])
    if max_results:
        items = items[:max_results]
    return {"resources": items}

def fake_subfolders(root):
    slugs = sorted({pid.split("/")[1] for pid in STORE if pid.startswith(f"{root}/")})
    return {"folders": [{"name": s, "path": f"{root}/{s}"} for s in slugs]}

def patch(module, name, fake):
    assert hasattr(module, name), f"{module.__name__}.{name} does not exist on the real cloudinary SDK"
    setattr(module, name, fake)

patch(appmod.cloudinary.api, "resources", fake_resources)
patch(appmod.cloudinary.api, "subfolders", fake_subfolders)
patch(appmod.cloudinary.api, "usage", lambda: {"credits": {"used_percent": 5}})

seed("ireland-2026", ["a.jpg", "b.jpg"])

results = []
def check(name, cond):
    print(f"{'OK  ' if cond else 'FAIL'} {name}")
    results.append(cond)

with appmod.app.test_client() as anon:
    r = anon.get("/")
    check("homepage loads without login", r.status_code == 200)
    check("nav shows 'Log in', not 'Upload', when logged out",
          b"Log in" in r.data and b">Upload<" not in r.data)

    r = anon.get("/album/ireland-2026")
    check("album page loads without login", r.status_code == 200)
    check("no 'Manage album' controls shown to an anonymous viewer",
          b"Manage album" not in r.data)
    check("no per-photo move/cover/delete controls shown to an anonymous viewer",
          b"photo-tile-controls" not in r.data)
    check("select/download controls ARE shown to an anonymous viewer",
          b"select-bar" in r.data and b"Download album" in r.data)

    r = anon.post("/album/ireland-2026/download", data={
        "public_ids": ["albums/ireland-2026/a.jpg"],
    })
    check("downloading a photo works without login", r.status_code == 302 and "fl_attachment" in r.headers["Location"])

    # every change still requires login
    r = anon.get("/upload")
    check("upload page still requires login", r.status_code == 302 and "/login" in r.headers["Location"])

    r = anon.post("/upload/sign", json={"existing_album": "ireland-2026"})
    check("upload signing still requires login", r.status_code == 302 and "/login" in r.headers["Location"])

    r = anon.post("/album/ireland-2026/rename", data={"new_title": "Nope"})
    check("rename still requires login", r.status_code == 302 and "/login" in r.headers["Location"])
    check("...and nothing actually changed", appmod.album_exists("ireland-2026"))

    r = anon.post("/album/ireland-2026/photo/albums/ireland-2026/a.jpg/delete", data={})
    check("photo delete still requires login", r.status_code == 302 and "/login" in r.headers["Location"])
    check("...and the photo is still there",
          any(p["public_id"] == "albums/ireland-2026/a.jpg" for p in appmod.list_photos("ireland-2026")))

    r = anon.post("/album/ireland-2026/delete", data={})
    check("album delete still requires login", r.status_code == 302 and "/login" in r.headers["Location"])
    check("...and the album survives", appmod.album_exists("ireland-2026"))

with appmod.app.test_client() as authed:
    authed.post("/login", data={"password": "testpass123"})
    r = authed.get("/album/ireland-2026")
    check("logged in: 'Manage album' controls appear", b"Manage album" in r.data)
    check("logged in: per-photo controls appear", b"photo-tile-controls" in r.data)
    check("logged in: nav shows Upload and Log out",
          b">Upload<" in r.data and b"Log out" in r.data)

print()
if all(results):
    print("ALL PUBLIC-ACCESS CHECKS PASSED")
else:
    print("SOME CHECKS FAILED")
    raise SystemExit(1)

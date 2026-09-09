import os
os.environ.setdefault("UPLOAD_PASSWORD", "testpass123")
os.environ.setdefault("SECRET_KEY", "test-secret")

import app as appmod

appmod.CLOUDINARY_CONFIGURED = True
appmod.cloudinary.config(cloud_name="test-cloud", api_key="test-key", api_secret="test-secret", secure=True)

STORE = {}
_counter = {"n": 0}

def _next_ts():
    _counter["n"] += 1
    return f"2026-09-10T00:00:{_counter['n']:02d}Z"

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

zip_calls = []
def fake_download_zip_url(**options):
    zip_calls.append(options)
    ids = "&".join(options.get("public_ids", []))
    return f"https://api.cloudinary.com/v1_1/test-cloud/image/generate_archive?public_ids={ids}"

def patch(module, name, fake):
    assert hasattr(module, name), f"{module.__name__}.{name} does not exist on the real cloudinary SDK"
    setattr(module, name, fake)

patch(appmod.cloudinary.api, "resources", fake_resources)
patch(appmod.cloudinary.utils, "download_zip_url", fake_download_zip_url)

seed("ireland-2026", ["a.jpg", "b.jpg", "c.jpg"])
seed("summer-2027", ["z.jpg"])

results = []
def check(name, cond):
    print(f"{'OK  ' if cond else 'FAIL'} {name}")
    results.append(cond)

with appmod.app.test_client() as anon:
    r = anon.post("/album/ireland-2026/download", data={"all": "1"})
    check("download requires login (redirects, no zip built)", r.status_code == 302 and "/login" in r.headers["Location"])

with appmod.app.test_client() as c:
    c.post("/login", data={"password": "testpass123"})

    r = c.post("/album/ireland-2026/download", data={})
    check("no selection -> redirects back to the album with nothing built",
          r.status_code == 302 and "/album/ireland-2026" in r.headers["Location"] and not zip_calls)

    r = c.post("/album/ireland-2026/download", data={"public_ids": ["albums/ireland-2026/a.jpg"]})
    check("exactly one photo -> redirects straight to its own attachment URL (no zip)",
          r.status_code == 302 and "fl_attachment" in r.headers["Location"]
          and "albums/ireland-2026/a.jpg" in r.headers["Location"] and not zip_calls)

    r = c.post("/album/ireland-2026/download", data={
        "public_ids": ["albums/ireland-2026/a.jpg", "albums/ireland-2026/b.jpg"],
    })
    check("two photos -> redirects to a Cloudinary-built zip", r.status_code == 302 and len(zip_calls) == 1)
    check("zip was built from exactly the two requested public_ids",
          sorted(zip_calls[-1]["public_ids"]) == ["albums/ireland-2026/a.jpg", "albums/ireland-2026/b.jpg"])

    zip_calls.clear()
    r = c.post("/album/ireland-2026/download", data={"all": "1"})
    check("'download whole album' pulls every photo currently in the album, not a client-supplied list",
          len(zip_calls) == 1 and sorted(zip_calls[-1]["public_ids"]) == [
              "albums/ireland-2026/a.jpg", "albums/ireland-2026/b.jpg", "albums/ireland-2026/c.jpg",
          ])

    zip_calls.clear()
    r = c.post("/album/ireland-2026/download", data={
        "public_ids": ["albums/ireland-2026/a.jpg", "albums/summer-2027/z.jpg"],
    })
    check("a public_id from a different album is dropped, not included in this album's download",
          len(zip_calls) == 0)  # only one valid id survives filtering -> single-file redirect, not a zip
    check("...and the surviving single photo still downloads directly",
          r.status_code == 302 and "albums/ireland-2026/a.jpg" in r.headers["Location"])

print()
if all(results):
    print("ALL DOWNLOAD CHECKS PASSED")
else:
    print("SOME CHECKS FAILED")
    raise SystemExit(1)

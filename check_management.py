import os
os.environ.setdefault("UPLOAD_PASSWORD", "testpass123")
os.environ.setdefault("SECRET_KEY", "test-secret")

import app as appmod

appmod.CLOUDINARY_CONFIGURED = True
appmod.cloudinary.config(cloud_name="test-cloud", api_key="x", api_secret="y", secure=True)

# ---------- an in-memory fake Cloudinary ----------
# Simulates just enough of the Admin/Upload API surface for our app to work
# against, so we can exercise rename/delete/reorder/cover logic without a
# real network call.

STORE = {}  # public_id -> {"folder": str, "context": {...}, "created_at": str}
_counter = {"n": 0}

def _next_ts():
    _counter["n"] += 1
    return f"2026-09-04T00:00:{_counter['n']:02d}Z"

def seed(slug, filenames):
    for name in filenames:
        pid = f"albums/{slug}/{name}"
        STORE[pid] = {"context": {}, "created_at": _next_ts()}

def fake_resources(type=None, prefix=None, max_results=None, context=None):
    items = [
        {"public_id": pid, "created_at": data["created_at"],
         "context": {"custom": data["context"]} if data["context"] else {}}
        for pid, data in STORE.items()
        if prefix is None or pid.startswith(prefix)
    ]
    items.sort(key=lambda r: r["created_at"])
    if max_results:
        items = items[:max_results]
    return {"resources": items}

def fake_resource(public_id, context=None):
    data = STORE[public_id]
    return {"public_id": public_id, "context": {"custom": data["context"]} if data["context"] else {}}

def fake_update_resource(public_id, context=None):
    STORE[public_id]["context"] = dict(context or {})
    return {"public_id": public_id}

def fake_delete_resources(public_ids):
    for pid in public_ids:
        STORE.pop(pid, None)
    return {"deleted": {pid: "deleted" for pid in public_ids}}

def fake_delete_resources_by_prefix(prefix):
    for pid in [k for k in STORE if k.startswith(prefix)]:
        STORE.pop(pid)
    return {}

def fake_delete_folder(folder):
    return {}

def fake_subfolders(root):
    slugs = sorted({pid.split("/")[1] for pid in STORE if pid.startswith(f"{root}/")})
    return {"folders": [{"name": s, "path": f"{root}/{s}"} for s in slugs]}

def fake_rename(from_id, to_id):
    STORE[to_id] = STORE.pop(from_id)
    return {"public_id": to_id}

appmod.cloudinary.api.resources = fake_resources
appmod.cloudinary.api.resource = fake_resource
appmod.cloudinary.api.update_resource = fake_update_resource
appmod.cloudinary.api.delete_resources = fake_delete_resources
appmod.cloudinary.api.delete_resources_by_prefix = fake_delete_resources_by_prefix
appmod.cloudinary.api.delete_folder = fake_delete_folder
appmod.cloudinary.api.subfolders = fake_subfolders
appmod.cloudinary.uploader.rename = fake_rename
appmod.cloudinary.api.usage = lambda: {"credits": {"used_percent": 5}}

# ---------- seed some data ----------
seed("ireland-2026", ["a.jpg", "b.jpg", "c.jpg"])

results = []
def check(name, cond):
    print(f"{'OK  ' if cond else 'FAIL'} {name}")
    results.append(cond)

with appmod.app.test_client() as c:
    c.post("/login", data={"password": "testpass123"})

    # --- reorder: move the first photo (a.jpg) down, should swap with b.jpg ---
    photos_before = appmod.list_photos("ireland-2026")
    check("initial order is a,b,c", [p["public_id"].split("/")[-1] for p in photos_before] == ["a.jpg", "b.jpg", "c.jpg"])

    r = c.post(f"/album/ireland-2026/photo/{photos_before[0]['public_id']}/move", data={"direction": "down"})
    check("move down redirects", r.status_code == 302)

    photos_after = appmod.list_photos("ireland-2026")
    order_after = [p["public_id"].split("/")[-1] for p in photos_after]
    check("order is now b,a,c after moving a down", order_after == ["b.jpg", "a.jpg", "c.jpg"])

    # move it back up
    c.post(f"/album/ireland-2026/photo/albums/ireland-2026/a.jpg/move", data={"direction": "up"})
    order_restored = [p["public_id"].split("/")[-1] for p in appmod.list_photos("ireland-2026")]
    check("order restored to a,b,c after moving back up", order_restored == ["a.jpg", "b.jpg", "c.jpg"])

    # moving the first photo further up should be a no-op (already at edge)
    c.post(f"/album/ireland-2026/photo/albums/ireland-2026/a.jpg/move", data={"direction": "up"})
    order_noop = [p["public_id"].split("/")[-1] for p in appmod.list_photos("ireland-2026")]
    check("moving the first photo up is a no-op", order_noop == ["a.jpg", "b.jpg", "c.jpg"])

    # --- set cover ---
    c.post("/album/ireland-2026/photo/albums/ireland-2026/b.jpg/cover", data={})
    photos = appmod.list_photos("ireland-2026")
    covers = [p["public_id"] for p in photos if p["is_cover"]]
    check("exactly one photo is marked cover", covers == ["albums/ireland-2026/b.jpg"])

    # switch cover to a different photo -> old cover flag should clear
    c.post("/album/ireland-2026/photo/albums/ireland-2026/c.jpg/cover", data={})
    photos = appmod.list_photos("ireland-2026")
    covers = [p["public_id"] for p in photos if p["is_cover"]]
    check("cover moved to c.jpg and only one cover exists", covers == ["albums/ireland-2026/c.jpg"])

    # --- delete a single photo ---
    r = c.post("/album/ireland-2026/photo/albums/ireland-2026/a.jpg/delete", data={})
    check("delete photo redirects", r.status_code == 302)
    remaining = [p["public_id"].split("/")[-1] for p in appmod.list_photos("ireland-2026")]
    check("a.jpg is gone, b and c remain", remaining == ["b.jpg", "c.jpg"])

    # --- rename album ---
    r = c.post("/album/ireland-2026/rename", data={"new_title": "Ireland Trip 2026"})
    check("rename redirects", r.status_code == 302)
    check("new slug 'ireland-trip-2026' exists", appmod.album_exists("ireland-trip-2026"))
    check("old slug 'ireland-2026' no longer exists", not appmod.album_exists("ireland-2026"))
    renamed_photos = [p["public_id"] for p in appmod.list_photos("ireland-trip-2026")]
    check("both remaining photos moved to new slug", all("ireland-trip-2026" in pid for pid in renamed_photos) and len(renamed_photos) == 2)

    # renaming to a name that collides with an existing album should be rejected
    seed("summer-2027", ["x.jpg"])
    r = c.post("/album/ireland-trip-2026/rename", data={"new_title": "Summer 2027"}, follow_redirects=True)
    check("rename to a colliding name is rejected", appmod.album_exists("ireland-trip-2026"))

    # --- delete whole album ---
    r = c.post("/album/summer-2027/delete", data={})
    check("delete album redirects", r.status_code == 302)
    check("summer-2027 fully gone", not appmod.album_exists("summer-2027"))

    # --- delete-album route requires login ---
with appmod.app.test_client() as anon:
    r = anon.post("/album/ireland-trip-2026/delete", data={})
    check("delete album requires login (redirects, doesn't delete)", r.status_code == 302)
    check("album survives an unauthenticated delete attempt", appmod.album_exists("ireland-trip-2026"))

print()
if all(results):
    print("ALL MANAGEMENT CHECKS PASSED")
else:
    print("SOME CHECKS FAILED")
    raise SystemExit(1)

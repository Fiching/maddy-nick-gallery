import os
os.environ.setdefault("UPLOAD_PASSWORD", "testpass123")
os.environ.setdefault("SECRET_KEY", "test-secret")

import app as appmod
import cloudinary.utils

appmod.CLOUDINARY_CONFIGURED = True
appmod.cloudinary.config(cloud_name="test-cloud", api_key="test-key", api_secret="test-secret", secure=True)

results = []
def check(name, cond):
    print(f"{'OK  ' if cond else 'FAIL'} {name}")
    results.append(cond)

with appmod.app.test_client() as anon:
    r = anon.post("/upload/sign", json={"new_album_title": "Ireland 2026"})
    check("sign endpoint requires login (redirects when logged out)", r.status_code == 302)

with appmod.app.test_client() as c:
    c.post("/login", data={"password": "testpass123"})

    r = c.post("/upload/sign", json={})
    check("no album chosen -> 400 with an error message", r.status_code == 400 and "error" in r.get_json())

    r = c.post("/upload/sign", json={"new_album_title": "Ireland Trip 2026!!"})
    check("new album title -> 200", r.status_code == 200)
    body = r.get_json()
    check("slug is slugified", body.get("slug") == "ireland-trip-2026")
    check("folder is under the albums root", body.get("folder") == "albums/ireland-trip-2026")
    check("cloud_name/api_key are present (needed by the browser to talk to Cloudinary)",
          body.get("cloud_name") == "test-cloud" and body.get("api_key") == "test-key")
    check("no caption -> no context field", "context" not in body)

    # the signature must be independently reproducible from the returned
    # params + the real api_secret, exactly like Cloudinary itself will
    # recompute it when the browser's upload request arrives
    params_to_sign = {
        "timestamp": body["timestamp"],
        "folder": body["folder"],
        "use_filename": body["use_filename"],
        "unique_filename": body["unique_filename"],
        "overwrite": body["overwrite"],
    }
    expected_sig = cloudinary.utils.api_sign_request(params_to_sign, "test-secret")
    check("signature matches independent recomputation", body["signature"] == expected_sig)

    # a caption should end up as an escaped context string, included in the
    # signature this time
    r = c.post("/upload/sign", json={"existing_album": "ireland-trip-2026", "caption": "Cliffs | of = Moher"})
    body = r.get_json()
    check("caption becomes an escaped context field", body.get("context") == "caption=Cliffs \\| of \\= Moher")
    params_to_sign = {
        "timestamp": body["timestamp"],
        "folder": body["folder"],
        "use_filename": body["use_filename"],
        "unique_filename": body["unique_filename"],
        "overwrite": body["overwrite"],
        "context": body["context"],
    }
    expected_sig = cloudinary.utils.api_sign_request(params_to_sign, "test-secret")
    check("signature with context matches independent recomputation", body["signature"] == expected_sig)

    # existing_album takes a raw slug from a <select>, but should still be
    # defensively slugified server-side rather than trusted verbatim
    r = c.post("/upload/sign", json={"existing_album": "Not/A Real Slug"})
    body = r.get_json()
    check("existing_album is slugified defensively too", body.get("slug") == "not-a-real-slug")

print()
if all(results):
    print("ALL SIGN-UPLOAD CHECKS PASSED")
else:
    print("SOME CHECKS FAILED")
    raise SystemExit(1)

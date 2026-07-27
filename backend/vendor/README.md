# Vendor wheels (not committed)

Drop the **HailoRT Python wheel** here to enable the Hailo-8 backend:

```
backend/vendor/hailort-<version>-cp312-cp312-linux_aarch64.whl
```

Where to get it: [Hailo Developer Zone](https://hailo.ai/developer-zone/) →
Software Downloads → HailoRT → *Python package*. An account is required, which
is why this cannot be fetched automatically by the build.

Three things must match or the runtime will refuse to load / talk to the device:

1. **HailoRT version** — the wheel version must equal the host's installed
   HailoRT: the native `libhailort.so.<version>` (`ls /usr/lib/libhailort.so.*`)
   AND the driver/firmware (`hailortcli fw-control identify`). The wheel only
   ships Python bindings; they dynamically link `libhailort.so.<version>`, which
   `docker-compose.hailo.yml` mounts in from the host — so if the wheel is 4.24.0
   but the host lib is 4.23.0, the import fails with
   `libhailort.so.4.24.0: cannot open shared object file`. Pick the wheel version
   that matches `/usr/lib/libhailort.so.*` on the host, and update the mount path
   in `docker-compose.hailo.yml` to the same version.
2. **Python version** — the container runs Python 3.12, so the wheel must be
   `cp312` and `linux_aarch64`.

The Docker build works fine with this directory empty; the Hailo option then
reports "HailoRT missing" on the Settings page and inference stays on CPU.

`.hef` model files do **not** go here — they belong in `models/models/hailo/`
on the host (bind-mounted into the container).

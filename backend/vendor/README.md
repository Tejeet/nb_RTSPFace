# Vendor wheels (not committed)

Drop the **HailoRT Python wheel** here to enable the Hailo-8 backend:

```
backend/vendor/hailort-<version>-cp312-cp312-linux_aarch64.whl
```

Where to get it: [Hailo Developer Zone](https://hailo.ai/developer-zone/) →
Software Downloads → HailoRT → *Python package*. An account is required, which
is why this cannot be fetched automatically by the build.

Two things must match or the runtime will refuse to talk to the device:

1. **Driver version** — the wheel version must equal the `hailort` PCIe driver
   version installed on the host (`hailortcli fw-control identify`).
2. **Python version** — the container runs Python 3.12, so the wheel must be
   `cp312` and `linux_aarch64`.

The Docker build works fine with this directory empty; the Hailo option then
reports "HailoRT missing" on the Settings page and inference stays on CPU.

`.hef` model files do **not** go here — they belong in `models/models/hailo/`
on the host (bind-mounted into the container).

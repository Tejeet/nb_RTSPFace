# Vendor wheels — HailoRT

Put **exactly one** HailoRT Python wheel here to enable the Hailo-8 backend:

```
backend/vendor/hailort-<version>-cp312-cp312-linux_aarch64.whl
```

> ⚠️ Keep only ONE `hailort*.whl` in this folder. The Docker build installs
> `vendor/hailort*.whl` (a glob) — two wheels means two conflicting installs.

## Required version for THIS deployment: 4.23.0

All four pieces must be the **same** HailoRT version, or `import hailo_platform`
fails at runtime with `libhailort.so.<version>: cannot open shared object file`:

| Piece | Where | Current |
| --- | --- | --- |
| PCIe driver + firmware | host, `hailortcli fw-control identify` | 4.23.0 |
| Native library `libhailort.so` | host, `ls /usr/lib/libhailort.so.*` | 4.23.0 |
| Python wheel (this folder) | `backend/vendor/` | **must be 4.23.0** |
| Library mount | `docker-compose.hailo.yml` | 4.23.0 |

So the correct file here is:

```
hailort-4.23.0-cp312-cp312-linux_aarch64.whl
```

The pip wheel ships only the Python bindings; they dynamically link the native
`libhailort.so.4.23.0`, which `docker-compose.hailo.yml` bind-mounts from the
host — the image never contains the licensed `.so`.

## Where to get it

[Hailo Developer Zone](https://hailo.ai/developer-zone/) → Software Downloads →
**HailoRT** → change the "Latest release" filter to **4.23.0** → Architecture
**ARM64**, OS **Linux**, Python **3.12** → download the `.whl`. An account is
required, so the build cannot fetch it automatically.

## If you upgrade HailoRT later

Bump all four together: install the new `hailort_<ver>_arm64.deb` +
`hailort-pcie-driver_<ver>_all.deb` on the host, reboot, then replace the wheel
here **and** update the mount path in `docker-compose.hailo.yml` to the new
`libhailort.so.<ver>`.

## Notes

- The build works with this folder empty — Hailo just reports "HailoRT missing"
  on the Settings page and inference stays on CPU.
- `.hef` model files do NOT go here — they live in `models/models/hailo/` on the
  host (bind-mounted into the container).

import storage

# Keep the filesystem writable so code.py can save configuration files
# This is necessary because CircuitPython defaults to read-only when USB is connected
storage.remount("/", readonly=False)

print("Filesystem mounted as writable")


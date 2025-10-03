import storage

# Production mode: disable USB mass storage, allow code to write files
storage.disable_usb_drive()
storage.remount("/", readonly=False)

print("=" * 50)
print("PRODUCTION MODE")
print("Filesystem writable from code")
print("USB mass storage disabled")
print("")
print("To enable USB for development:")
print("Hold button for 10 seconds to enter Safe Mode")
print("=" * 50)


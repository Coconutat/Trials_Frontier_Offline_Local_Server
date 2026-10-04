#!/system/bin/sh
# Trials Frontier: bind-mount the game's private files/ dir onto shared storage.
#
#   /data/data/<PKG>/files  <-  /data/media/0/Android/data/<PKG>/files
#
# Why the *ext4* path (/data/media/...) instead of /sdcard/... :
#   /sdcard/Android/data is a sdcardfs view; binding that view makes the game
#   read/write through sdcardfs, which breaks it (the IAP "portal" lookup comes
#   back NULL and IAPManager_CallInit() segfaults in strcmp on the first frame).
#   Binding the underlying ext4 directory keeps normal ext4 semantics for the
#   game while the very same inodes stay visible (and editable) to any file
#   manager under /sdcard/Android/data/<PKG>/files.
#
# Idempotent: safe to run from post-fs-data.d and service.d, and by hand.

PKG=com.ubisoft.redlynx.trialsfrontier.ggp
SRC=/data/media/0/Android/data/$PKG/files
DST=/data/data/$PKG/files

[ -d /data/media/0/Android/data/$PKG ] || exit 0

# Source must be a real directory, never a symlink back into /data/data.
if [ -L "$SRC" ]; then
  echo "tf_files_bind: $SRC is a symlink, refusing"
  exit 1
fi
[ -d "$SRC" ] || mkdir -p "$SRC" || exit 1

if grep -q " $DST " /proc/mounts 2>/dev/null; then
  exit 0                       # already bound
fi

if [ -L "$DST" ]; then         # leftover of the old symlink approach
  rm -f "$DST" || exit 1
fi
[ -d "$DST" ] || mkdir -p "$DST" || exit 1

mount --bind "$SRC" "$DST" || exit 1
echo "tf_files_bind: bound $SRC -> $DST"
exit 0

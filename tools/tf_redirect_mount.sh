#!/system/bin/sh
# Trials Frontier: bind-mount the game's private files/ dir onto shared storage.
#
#   /data/data/<PKG>/files  <-  /data/media/0/Android/data/<PKG>/files
#
# so that saves, ghosts and downloaded content packs live in a directory the
# user can reach with any file manager / backup tool, while the game keeps
# seeing them at its own private path.
#
# Why the *ext4* path (/data/media/...) instead of /sdcard/... :
#   /sdcard/Android/data is a sdcardfs view. Binding that view makes the game
#   go through sdcardfs instead of plain ext4, so bind the underlying ext4
#   directory: the very same inodes stay visible under
#   /sdcard/Android/data/<PKG>/files, but the game gets normal ext4 semantics.
#
# ★ Why ownership matters (this cost us hours -- do not skip it):
#   after any move, EVERY file must end up owned by the app uid with group
#   sdcard_rw.  If they are left root-owned the game starts, then segfaults
#   ~5 s later with ZERO network traffic.  Tombstone:
#     __strcmp_aarch64 <- libTrialsGo.so 0x8b4c18 <- 0x8b4dcc
#     <- mz::IAPManagerAndroid::queryProducts+500
#     <- mz::IAPManager::queryProducts+124
#     <- tr::StoreManager::reinit+396 <- tr::StoreManager::init+40
#     <- tr::GlobalData::init+1216 <- tr::MainApp::init+112
#   It is the game's own upstream bug: IAPManager_CallInit's wrapper finds a
#   NULL "portal" name, only logs
#   "IAP called on an unvailable store. Please check your db file" and then
#   falls through to strcmp("Google Play", NULL).
#
# Idempotent: safe to run from post-fs-data.d / service.d and by hand.

PKG=com.ubisoft.redlynx.trialsfrontier.ggp
PKGDIR=/data/data/$PKG
SRC=/data/media/0/Android/data/$PKG/files
DST=$PKGDIR/files

# uid of the app, gid of shared storage (robust on toybox: no `stat -c`)
UID_APP=$(ls -ldn "$PKGDIR" 2>/dev/null | awk '{print $3}')
GID_APP=$(ls -ldn /data/media/0/Android/data/$PKG 2>/dev/null | awk '{print $4}')
[ -n "$UID_APP" ] || UID_APP=10296
[ -n "$GID_APP" ] || GID_APP=1015

fix_owner() {
  chown -R "$UID_APP:$GID_APP" "$SRC" 2>/dev/null
  chmod 2771 "$SRC" 2>/dev/null
  restorecon -R "$SRC" 2>/dev/null
}

# /data/media/0 is not ready that early at post-fs-data; service.d will get it.
[ -d /data/media/0/Android/data/$PKG ] || exit 0

# Never let the shared dir be a symlink pointing back into /data/data.
if [ -L "$SRC" ]; then
  echo "tf_files_bind: $SRC is a symlink, refusing"
  exit 1
fi
mkdir -p "$SRC" || exit 1

if grep -q " $DST " /proc/mounts 2>/dev/null; then
  fix_owner                     # already bound: just make sure it is sane
  exit 0
fi

# --- first run: migrate the private dir out to shared storage -------------
if [ -L "$DST" ]; then          # leftover of the old symlink approach
  rm -f "$DST" || exit 1
fi
mkdir -p "$DST" || exit 1

moved=0
for f in $(ls -A "$DST" 2>/dev/null); do
  if [ -e "$SRC/$f" ]; then
    # name already exists in shared storage: keep the shared copy, drop the
    # private one only if it really is the same-or-older leftover
    rm -rf "$DST/$f" && moved=$((moved+1))
    continue
  fi
  mv "$DST/$f" "$SRC/" && moved=$((moved+1))
done
[ "$moved" -gt 0 ] && echo "tf_files_bind: migrated $moved entries"

fix_owner

mount --bind "$SRC" "$DST" || exit 1
echo "tf_files_bind: bound $SRC -> $DST (uid=$UID_APP gid=$GID_APP)"
exit 0

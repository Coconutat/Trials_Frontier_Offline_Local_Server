#!/system/bin/sh
# Undo tf_redirect_mount.sh: put the game's files back into its private dir.
#
#   /data/data/<PKG>/files   (real dir, ext4, app_data_file)
#
# The OBB/expansion files (content.dat, contentSFX.dat, textures_android.dat,
# tf_server.txt, vungle_cache) always belonged in shared storage and stay there.
#
# ★ Ownership is fixed up from the *package* dir, never from $DST: right after
#   `mkdir` the private dir can be root-owned, and deriving the uid from it
#   would chown the whole game data to root -- which makes the game segfault in
#   IAPManager_CallInit (see tools/tf_redirect_mount.sh for the tombstone).

PKG=com.ubisoft.redlynx.trialsfrontier.ggp
PKGDIR=/data/data/$PKG
SRC=/data/media/0/Android/data/$PKG/files
DST=$PKGDIR/files

echo "== stop the game =="
am force-stop $PKG
sleep 2

echo "== umount $DST =="
for m in "$DST" \
         /data/user/0/$PKG/files \
         /data_mirror/data_ce/null/0/$PKG/files \
         /data_mirror/data_ce/$PKG/files; do
  [ -d "$m" ] || continue
  umount "$m" 2>/dev/null
done
if grep -q " $DST " /proc/mounts 2>/dev/null; then
  echo "!! still mounted, aborting so we do not move data under a live mount"
  exit 1
fi

[ -L "$DST" ] && rm -f "$DST"
[ -d "$DST" ] || mkdir -p "$DST"

echo "== move game data back from $SRC =="
cd "$SRC" || exit 1
i=0
for f in $(ls -A); do
  case "$f" in
    content.dat|contentSFX.dat|textures_android.dat|tf_server.txt|vungle_cache)
      continue ;;
  esac
  mv "$f" "$DST/" && i=$((i+1))
done
echo "   moved $i entries"

UID_APP=$(ls -ldn "$PKGDIR" | awk '{print $3}')
GID_APP=$(ls -ldn "$PKGDIR" | awk '{print $4}')
[ -n "$UID_APP" ] || UID_APP=10296
[ -n "$GID_APP" ] || GID_APP=10296
chown -R "$UID_APP:$GID_APP" "$DST" 2>/dev/null
chmod 771 "$DST" 2>/dev/null
restorecon -R "$DST" 2>/dev/null

echo "== check =="
ls -ldn "$DST"
ls -A "$DST" | head -5
echo "   total $(ls -A "$DST" | wc -l) entries"
echo "== done =="

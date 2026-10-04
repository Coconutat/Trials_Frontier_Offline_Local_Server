#!/system/bin/sh
# Undo tf_redirect_mount.sh: put the game's files back into its private dir.
#
#   /data/data/<PKG>/files   (real dir, ext4, app_data_file)
#
# The OBB/expansion files (content.dat, contentSFX.dat, textures_android.dat,
# tf_server.txt, vungle_cache) always belonged in shared storage and stay there.

PKG=com.ubisoft.redlynx.trialsfrontier.ggp
SRC=/data/media/0/Android/data/$PKG/files
DST=/data/data/$PKG/files

echo "== stop the game =="
am force-stop $PKG
sleep 2

echo "== umount $DST =="
if grep -q " $DST " /proc/mounts 2>/dev/null; then
  umount "$DST" || { echo "!! umount failed"; exit 1; }
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

UID_APP=$(ls -ldn "$DST" | awk '{print $3}')
GID_APP=$(ls -ldn "$DST" | awk '{print $4}')
chown -R "$UID_APP:$GID_APP" "$DST" 2>/dev/null
restorecon -R "$DST" 2>/dev/null

echo "== check =="
ls -A "$DST" | head -5
echo "   total $(ls -A "$DST" | wc -l) entries"
echo "== done =="

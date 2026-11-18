"""Per-user, per-device backups, independent of install folder and drive letter."""
import json
import os
import shutil
from datetime import datetime, timezone, timedelta
from pathlib import Path
from lg700_core import sha256, restore_file
from device_profiles import LG700_PROFILE, check_manifest_device

FACTORY_IMPORT = 'factory_asset_import'


def data_home():
    root = Path(os.environ.get("LOCALAPPDATA", str(Path.home() / "AppData/Local")))
    return root / "TCOMAS-LG700-Tool"


def device_home(device):
    path = device.info.get('path', b'')
    if isinstance(path, bytes):
        path = path.decode(errors='replace')
    serial = device.info.get("serial_number") or path
    identity = str(device.info.get("product_string", "LG700")) + "|" + serial
    key = sha256(identity.encode("utf8"))[:16]
    directory = data_home() / "Backups"
    # Preserve existing LG700 Original backups at their historical paths.
    if device.profile != LG700_PROFILE:
        directory /= device.profile.name
    return directory / key


def new_snapshot(device, suffix):
    stamp = datetime.now(timezone(timedelta(hours=8))).strftime("%Y%m%d_%H%M%S_%f")
    return device_home(device) / (stamp + "_" + suffix)


def preserve_original(device, snapshot):
    original = device_home(device) / "Original"
    if original.exists():
        # Never replace the first valid original with later custom animations.
        restore_file(original, 1, profile=device.profile, allow_empty=True)
        restore_file(original, 0, profile=device.profile)
        return original
    original.parent.mkdir(parents=True, exist_ok=True)
    temporary = original.with_name("Original.pending")
    if temporary.exists():
        raise RuntimeError("存在未完成的原始备份，请先检查 Original.pending 目录")
    shutil.copytree(snapshot, temporary)
    restore_file(temporary, 1, profile=device.profile, allow_empty=True)
    restore_file(temporary, 0, profile=device.profile)
    temporary.rename(original)
    return original


def original_directory(device):
    directory = device_home(device) / "Original"
    if not (directory / "manifest.json").is_file():
        raise FileNotFoundError("此电脑尚无该屏幕的原始备份，请先备份或导入原始备份目录")
    return directory


def restore_manifest(directory, device, *, allow_import=False, allow_cross_revision=False):
    manifest = json.loads((Path(directory) / 'manifest.json').read_text(encoding='utf8'))
    check_manifest_device(manifest, device.profile,
                          revision=None if allow_cross_revision else device.revision,
                          info=device.info)
    if manifest.get('kind') == FACTORY_IMPORT:
        if not allow_import:
            raise ValueError('导入包需要手动选择')
        source = manifest.get('source_backup', {}).get('device', {})
        target = manifest['device']
        check_manifest_device({'device': source}, device.profile, info=device.info)
        if (not target.get('device_key') or
                any(source.get(key) != target.get(key) for key in ('vid', 'pid')) or
                manifest.get('device_role') != 'import_target_not_capture' or
                any(manifest['assets'][name].get('file') != f'{name}.bin' for name in ('boot', 'standby'))):
            raise ValueError('导入包必须绑定当前设备，并保留同型号素材的来源信息')
    return manifest


def convert_original_assets(directory, device, *, allow_import=False):
    """Check same-device assets for a cross-revision restore attempt.

    Validating the container and JPEGs does not prove firmware compatibility.
    The caller must still back up the live assets and verify actual writes.
    """
    restore_manifest(directory, device, allow_import=allow_import, allow_cross_revision=True)
    # Preserve the source bytes and its recorded revision. The fresh backup
    # of the connected device, not this older source, authorizes the write.
    return {s: restore_file(directory, s, profile=device.profile) for s in (1, 0)}

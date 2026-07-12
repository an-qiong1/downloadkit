# 飞牛 NAS 影视库部署资产

本目录用于完成 `MoviePilot + qBittorrent + Jellyfin` 影视库部署。

当前状态：

- 本机已有 SSH 公钥：`C:\Users\l2606\.ssh\id_rsa.pub`
- NAS 尚未接受该公钥，`ssh -o BatchMode=yes wuyang@192.168.5.15 "hostname"` 仍失败
- 因此远程执行前，需要先把公钥加入 NAS 用户 `wuyang` 的 `~/.ssh/authorized_keys`

## 1. 先配置 SSH 免密

在本机查看公钥：

```powershell
Get-Content "$env:USERPROFILE\.ssh\id_rsa.pub"
```

把输出内容追加到 NAS 用户 `wuyang` 的：

```text
~/.ssh/authorized_keys
```

然后验证：

```powershell
ssh -o BatchMode=yes wuyang@192.168.5.15 "hostname"
```

## 2. 上传部署资产

免密成功后，在本机运行：

```powershell
powershell -ExecutionPolicy Bypass -File "C:\Users\l2606\Documents\资源下载\scripts\nas-media-library\deploy-assets.ps1"
```

脚本会把 `nas/` 和 `assets/` 上传到：

```text
/vol1/1000/影视/scripts/nas-media-library
```

## 3. 推荐执行顺序

先只读盘点：

```bash
bash /vol1/1000/影视/scripts/nas-media-library/inventory.sh
bash /vol1/1000/影视/scripts/nas-media-library/check-moviepilot-patches.sh
bash /vol1/1000/影视/scripts/nas-media-library/verify-services.sh
```

确认无异常后备份并应用补丁：

```bash
bash /vol1/1000/影视/scripts/nas-media-library/backup-moviepilot.sh
bash /vol1/1000/影视/scripts/nas-media-library/apply-moviepilot-patches.sh
bash /vol1/1000/影视/scripts/nas-media-library/check-moviepilot-patches.sh
```

## 4. 注意事项

- 不升级 MoviePilot 镜像，避免现有补丁失效。
- 不删除现有下载和媒体文件。
- Jellyfin API Key 不写入本目录和知识库文档。
- `cleanup-temp.sh` 只会列出候选临时文件，默认不删除。

# 称号图标资源

本目录保存全部 83 个现有徽章的图标；称号池从中选择 61 个徽章（4 UR + 7 SSR + 20 SR + 30 R），另有 50 个随机 N 暂不配图标。数据快照为 2026-11-03。

## 目录结构

| 路径 | 内容 |
|---|---|
| `custom/*.png` | 8 个徽章的自定义图片，按徽章 ID 命名 |
| `fa/*.svg` | 34 个去重后的 Font Awesome 6.7.2 图标，按 `样式_图标名.svg` 命名 |
| `icons.json` | 83 个徽章到图标文件的完整映射，含来源、图标名、格式与字节数 |

## 使用方式

- 后端/前端只需读取 `icons.json`：以称号 `code`（`li_badge_<徽章ID>`）为键，取 `file` 字段拼接本目录路径即可。
- `kind` 为 `custom_image` 时是徽章原图；为 `fontawesome` 时是 Font Awesome SVG。
- 多个称号会复用同一个 SVG 文件（例如所有“赞”类徽章共用 `fa/solid_heart.svg`），这是预期行为。

## 映射说明

- 原徽章 `icon` 字段为 `vote-up-filled` 时，Font Awesome Free 没有同名图标，已用 `fa/solid_chevron-up.svg` 替代；`icons.json` 同时保留原始 `icon` 与替代的 `fa_name`。
- `fab-` 前缀映射到 Font Awesome Brands，`far-` 前缀映射到 Regular，其余映射到 Solid。
- 如果后续徽章图标变更，保留称号 `code`，只更新 `file` 与 `source`，不要改 `code`。

## 授权

- Font Awesome Free 6.7.2 图标遵循 CC BY 4.0，使用时保留本说明即可。
- `custom/` 下的徽章图片来自 linux.do，版权归站点及原作者所有；仅用于本项目称号展示，商用或再分发前请先确认授权。

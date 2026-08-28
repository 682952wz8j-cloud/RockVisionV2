# Incoming wall data

This folder is where you put new wall data. You do not need to know how
the computer works.

Files you put here are **originals**. RockVision will not rename them,
edit them, or delete them.

---

## How to add a new wall

1. Create a folder named `wall_` plus the wall ID.

   Example: `incoming/wall_jiulongfeng_01/`

2. Copy the complete original folders from the drone, phone, modeling
   software, CloudCompare, or any other source into that folder.
   Leave the export as it came from the device or software.

3. Also put models, route files, or other related originals directly
   into the same wall folder. Nested folders are fine.

4. You do **not** need to sort files into photos / model / routes /
   metadata.

5. You do **not** need to rename files.

6. Do **not** delete RTK, GNSS, or other files you do not understand.
   Keep them.

7. Run the ingestion command from the project folder:

   ```text
   ./rockvision ingest wall_jiulongfeng_01
   ```

   If that wrapper is not available, this is the same command:

   ```text
   python3 tools/rockvision.py ingest wall_jiulongfeng_01
   ```

   To run the Phase 1 gate-aware wall build (discovery, preflight, ingest, qualify, then stop before unapproved stages):

   ```text
   ./rockvision build wall_<id>
   ```

The command only reads `incoming/`. It writes a file list and a report
under `offline/work/wall_<id>/ingestion/`.

You can add more capture folders later for the same wall:

```text
incoming/wall_jiulongfeng_01/
    DJI_flight_001/
    DJI_flight_002/
    iphone_capture_001/
    cloudcompare_export/
```

Folder names are yours. The tool looks at the files, not the folder names.

---

## 如何新增一面墙

1. 新建文件夹 `incoming/wall_<墙ID>/`
2. 把无人机、手机或其他软件导出的**完整原始文件夹**复制进去
3. 模型、线路和其他原始文件也直接放进去
4. 不需要人工分类
5. 不需要改文件名
6. 不要删除看不懂的 RTK / GNSS / 辅助文件
7. 运行：`./rockvision ingest wall_<墙ID>`

   或 Phase 1 编排：`./rockvision build wall_<墙ID>`

不要改动 `incoming/` 里的原文件。

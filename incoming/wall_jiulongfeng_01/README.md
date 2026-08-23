# 放入待导入的建筑物模型与线路

把文件放到这个目录后，在 RockVision 会话里说「数据已放到 _incoming」。

## 建议结构

```text
_incoming/
  model/                 建筑物网格（优先 USDZ，或 OBJ+贴图 / GLB）
  route_1.poly           每行 x y z，单位米
  route_2.poly
  README.txt             坐标系、哪轴向上、原点在哪、单位
```

`.poly` 格式：空格分隔的 `x y z`，至少 2 个点，与模型同一坐标系。

## 导入后会显示的线路信息

| 线路 | 难度 | 挂片 |
|------|------|------|
| route 1 | 5.10a | 5 |
| route 2 | 5.12b | 6 |

长度按折线点距自动计算。默认半透明蓝；点选后鲜黄，并展示定线/开线、首攀、评分、评论。

若已有定线者、首攀、评分、评论，可放在同目录 `routes_meta.json`，例如：

```json
{
  "route_1": {
    "setter": { "name": "", "date": "" },
    "firstAscent": { "name": "", "date": "" },
    "rating": 4.5,
    "comments": [
      { "id": "c1", "author": "", "date": "", "text": "" }
    ]
  }
}
```

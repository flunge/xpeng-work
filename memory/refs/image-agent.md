---
name: image-agent
description: 图像全流程Agent — 读图/生图/贴图/跨文档搬图，能力矩阵+踩坑记录
metadata: 
  node_type: memory
  type: reference
  originSessionId: 1b82ee7e-8c3b-4c47-81c6-9b8342353437
---

# 图像全流程 Agent

## 能力矩阵

| 场景 | 方式 | 自动 |
|------|------|:--:|
| **读图**（理解文档中图片内容） | `docs +media-download` → Agent(model: sonnet) 视觉分析 | ✅ |
| **搬图**（跨文档复制已有图） | `block_copy_insert_after` + `block_replace` 换图源 | ✅ |
| **生图**（GPT-Image-2 生成新图） | SoCheap API → 存本地 → 用户 `/image` 手动贴 | ⚠️ 半自动 |
| **贴新图到 Wiki** | ❌ API 插入均为方形框 | ❌ |

## 一、读图

```bash
# 1. 列出文档所有图片的 src token
lark-cli docs +fetch --api-version v2 --doc "<url>" --format json | \
  python3 -c "import json,sys,re; content=json.load(sys.stdin)['data']['document']['content']; \
  imgs=re.findall(r'src=\"([^\"]+)\"', content); print('\n'.join(imgs))"

# 2. 下载
lark-cli docs +media-download --token "<src>" --output img.png

# 3. 分析：Agent(model: sonnet) 读取图片，结合上下文分析
```

Sonnet Agent 有原生视觉能力，能识别图表类型、提取具体数值、理解信息传达意图。每次分析 ~25k tokens。

## 二、搬图（跨文档复制已有图）

```bash
# 1. 在目标文档找一个渲染正确的图做模板
# 2. block_copy_insert_after 复制它
lark-cli docs +update --api-version v2 --doc "<target>" \
  --command block_copy_insert_after \
  --block-id "<template_img_id>" --src-block-ids "<template_img_id>"

# 3. 上传源文档的图到目标文档
cp source_img.png ./tmp.png
FT=$(lark-cli docs +media-upload --file tmp.png --doc-id "<doc_id>" \
  --parent-node "<parent_id>" --parent-type docx_image --format json | \
  python3 -c "import json,sys; print(json.load(sys.stdin)['data']['file_token'])")

# 4. 替换模板 block 的图源
lark-cli docs +update --api-version v2 --doc "<target>" \
  --command block_replace --block-id "<copied_block_id>" \
  --content "<img src=\"$FT\" mime=\"image/png\"/>"
rm -f tmp.png
```

## 三、生图（GPT-Image-2）

- 模型：`gpt-image-2`，1K 分辨率，16:9，~$0.03/张
- 生成耗时 ~45秒
- 中文 prompt，信息要全，明确说 "Fill the entire frame, no white space"
- API key 在 `pipelines/media_key.txt`

**生图后流程**：
1. 存到 `/Users/xpeng/Documents/team/projects/GIC_report/<name>.png`
2. 文档中写 `【贴图：<name>.png】` 占位标记
3. 用户 `/image` 手动上传，删标记

## 四、裁剪白边

搬图前自动裁剪图片四周的白边/浅色边，让图在文档里更紧凑：

```python
from PIL import Image, ImageChops

def trim_white(img_path, border_threshold=30):
    """裁剪图片四周的白边。threshold越小越激进"""
    img = Image.open(img_path)
    if img.mode != 'RGB':
        img = img.convert('RGB')
    bg = Image.new('RGB', img.size, (255, 255, 255))
    diff = ImageChops.difference(img, bg).convert('L')
    # 阈值：diff>threshold 的像素算"有内容"
    mask = diff.point(lambda p: 255 if p > border_threshold else 0)
    bbox = mask.getbbox()
    if bbox:
        return img.crop(bbox)
    return img
```

- 默认 threshold=30，可调。会议纪要里的截图/图表通常 threshold=20-40 效果好
- 搬图流程中，在 `media-download` 之后、`media-upload` 之前执行裁剪

## 五、踩坑记录

- ❌ Wiki 文档 API 插入新图 → 方形框（h1/li/裸img/grid/各种scale 均无效）
- ❌ `<img file-token="xxx"/>` → 图不渲染，必须用 `src`
- ❌ 标注"Grok生成"/"GPT生成" → 暴露工具名
- ❌ `--file` 绝对路径 → lark-cli 拒绝
- ❌ `--doc-id` 用 wiki token → 必须用内部 document_id
- ❌ 反复测试生图 → 浪费 $0.03/次，prompt 想好再发
- ❌ `block_insert_after` 插入 `<img>` 不带 `crop` 和 `scale` → 图片 block 下方产生大片白边

### 消除图片白边

`block_insert_after` 插入的图片 block 默认长宽比不对，下方有大片白边。用 `block_replace` 补上 `crop` 和 `scale` 属性：

```bash
lark-cli docs +update --api-version v2 --doc "<url>" \
  --command block_replace --block-id "<img_block_id>" \
  --content '<img crop="[0,0,1,1]" mime="image/png" scale="0.50" src="<file_token>"/>'
```

- `crop="[0,0,1,1]"` = 不裁剪原图
- `scale` = 显示比例，按图片实际宽度/列宽估算（1920px图→0.4，900px图→0.5，参考值）

## 五、技术原理

```
主对话（deepseek-v4-pro，无视觉）
  └── Agent 工具
        ├── model: "sonnet"  → Claude Sonnet 4.6，有视觉 → 读图
        ├── model: "opus"   → Claude Opus 4.8，有视觉
        └── model: "haiku"  → Claude Haiku 4.5，有视觉
```

Sonnet/Opus 是 Claude Code 内置提供的，不需要第三方 API key。读图时 Agent 用 Read 工具打开 PNG/JPG，利用原生视觉能力分析像素内容。

// HTML(片段) → SVG，用 satori。字体用提取出的 Noto Sans CJK SC Bold。
// 用法: node html2svg.mjs <htmlfile> <outsvg> [width] [height]
import satori from 'satori';
import { html } from 'satori-html';
import fs from 'fs';

const [,, htmlFile, outSvg, wArg, hArg] = process.argv;
const W = parseInt(wArg || '1024', 10);
const H = parseInt(hArg || '576', 10);

const fontData = fs.readFileSync('/workspace/team/scripts/fonts/NotoSansCJKsc-Bold.ttf');
const markup = html(fs.readFileSync(htmlFile, 'utf8'));

try {
  const svg = await satori(markup, {
    width: W,
    height: H,
    fonts: [{ name: 'Noto Sans CJK SC', data: fontData, weight: 700, style: 'normal' }],
  });
  fs.writeFileSync(outSvg, svg);
  console.log('OK ->', outSvg, `(${svg.length} bytes)`);
} catch (e) {
  console.log('SATORI_ERR:', e.message);
  process.exit(1);
}

/* ============================================================
   main.js — 翻页导航 / 键盘 / 进度条 / 页码 / 全屏 / Logo 注入
   ============================================================ */
import './styles/tokens.css';
import './styles/base.css';
import './styles/hud.css';
import './styles/components.css';

// public/ 下的静态资源按 URL 引用（构建后复制到 dist 根目录）
const logoUrl = `${import.meta.env.BASE_URL}assets/xpeng-logo.svg`;

const STAGE_W = 1280;
const STAGE_H = 720;

const stage = document.getElementById('stage');
const slides = Array.from(document.querySelectorAll('.slide'));
const total = slides.length;
let current = 0;

/* —— 1. 为每页右上角注入统一 XPENG Logo（AC2.1 / AC2.2）—— */
slides.forEach((slide) => {
  if (slide.querySelector('.slide-logo')) return;
  const img = document.createElement('img');
  img.src = logoUrl;
  img.className = 'slide-logo';
  img.alt = 'XPENG';
  slide.appendChild(img);
});

/* —— 2. 16:9 舞台等比缩放适配 —— */
function fitStage() {
  const scale = Math.min(
    window.innerWidth / STAGE_W,
    window.innerHeight / STAGE_H
  );
  stage.style.transform = `scale(${scale})`;
}

/* —— 3. 翻页 —— */
function go(index) {
  current = Math.max(0, Math.min(total - 1, index));
  slides.forEach((s, i) => s.classList.toggle('is-active', i === current));
  updateChrome();
  if (location.hash !== `#${current + 1}`) {
    history.replaceState(null, '', `#${current + 1}`);
  }
}
const next = () => go(current + 1);
const prev = () => go(current - 1);

/* —— 4. 进度条 + 页码 —— */
function updateChrome() {
  const progress = document.getElementById('progress');
  const pager = document.getElementById('pager');
  progress.style.width = `${((current + 1) / total) * 100}%`;
  pager.innerHTML = `<span class="cur">${String(current + 1).padStart(2, '0')}</span> / ${total}`;
}

/* —— 5. 键盘 —— */
window.addEventListener('keydown', (e) => {
  // 编辑文本时不拦截方向键
  if (e.target.isContentEditable) return;
  switch (e.key) {
    case 'ArrowRight':
    case 'PageDown':
    case ' ':
      e.preventDefault(); next(); break;
    case 'ArrowLeft':
    case 'PageUp':
      e.preventDefault(); prev(); break;
    case 'Home':
      e.preventDefault(); go(0); break;
    case 'End':
      e.preventDefault(); go(total - 1); break;
    case 'f':
    case 'F':
      toggleFullscreen(); break;
    default: break;
  }
});

function toggleFullscreen() {
  if (!document.fullscreenElement) {
    document.documentElement.requestFullscreen?.();
  } else {
    document.exitFullscreen?.();
  }
}

/* —— 6. 按钮 —— */
document.getElementById('nav-prev').addEventListener('click', prev);
document.getElementById('nav-next').addEventListener('click', next);

/* —— 7. hash 定位 —— */
function fromHash() {
  const n = parseInt(location.hash.replace('#', ''), 10);
  if (!Number.isNaN(n) && n >= 1 && n <= total) go(n - 1);
  else go(0);
}
window.addEventListener('hashchange', fromHash);

/* —— init —— */
window.addEventListener('resize', fitStage);
fitStage();
fromHash();

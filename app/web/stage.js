// stage.js — 大肥鱼桌宠钛坦屏 640×480 水冷舞台核心中枢（支持双宠同屏、单宠独立与混排）

(function () {
  'use strict';

  // DOM 节点引用
  const bgLayer = document.getElementById('bg-layer');
  const coopContainer = document.getElementById('coopanion-container');
  const coopFrame = document.getElementById('coopanion-frame');
  const coopOffline = document.getElementById('coopanion-offline');

  const dshContainer = document.getElementById('dsh-container');
  const videoA = document.getElementById('video-a');
  const videoB = document.getElementById('video-b');
  const bubbleEl = document.getElementById('bubble-container');
  const bubbleText = document.getElementById('bubble-text');
  const memeWrapper = document.getElementById('bubble-meme-wrapper');
  const memeImg = document.getElementById('bubble-meme-img');
  const balancePill = document.getElementById('balance-pill');
  const balanceText = document.getElementById('balance-text');
  const statusPill = document.getElementById('status-pill');
  const statusText = document.getElementById('status-text');

  // 状态变量
  let activeVideo = videoA;
  let idleVideo = videoB;
  let currentAnimName = '';
  let bubbleTimer = null;
  let balanceTimer = null;
  let currentMode = 'dual';
  let currentLayout = 'side_by_side';
  let coopanionLoaded = false;

  // 默认休闲动作轮播列表
  const IDLE_ANIMATIONS = [
    '待机呼吸休闲',
    '原地专心玩魔方',
    '悠闲哼歌',
    '原地漂浮踏步',
    '吃白饭',
    '深度思考碎碎念',
    '吃Token'
  ];

  function getAnimUrl(name) {
    if (!name.endsWith('.webm')) name += '.webm';
    return `/assets/webm/${encodeURIComponent(name)}`;
  }

  function getMemeUrl(memeName) {
    if (!memeName) return '';
    if (!memeName.endsWith('.png') && !memeName.endsWith('.jpg')) memeName += '.png';
    return `/assets/memes/${encodeURIComponent(memeName)}`;
  }

  let lastAnimTime = 0;

  /**
   * 双缓冲平滑播放 WebM 动作
   */
  function playAnim(animName, loop = false) {
    const now = Date.now();
    if (animName === currentAnimName) {
      if (activeVideo.loop && !activeVideo.paused) return;
      if (now - lastAnimTime < 1500 && !activeVideo.paused) return;
    }
    lastAnimTime = now;
    currentAnimName = animName;
    const url = getAnimUrl(animName);

    idleVideo.src = url;
    idleVideo.loop = loop;
    idleVideo.playbackRate = 1.0;

    idleVideo.oncanplay = () => {
      idleVideo.play().then(() => {
        idleVideo.classList.add('is-front');
        activeVideo.classList.remove('is-front');
        const prev = activeVideo;
        activeVideo = idleVideo;
        idleVideo = prev;
        setTimeout(() => {
          if (idleVideo !== activeVideo) idleVideo.pause();
        }, 300);
      }).catch(err => {
        console.warn('[stage] 播放 WebM 失败:', err);
      });
    };

    idleVideo.onended = () => {
      if (!loop) {
        setTimeout(playRandomIdle, 1000 + Math.random() * 2000);
      }
    };
  }

  function playRandomIdle() {
    const idx = Math.floor(Math.random() * IDLE_ANIMATIONS.length);
    playAnim(IDLE_ANIMATIONS[idx], false);
  }

  function showSay(text, memeName = '', duration = 4500) {
    if (!text) return;
    bubbleText.textContent = text;
    if (memeName) {
      const url = getMemeUrl(memeName);
      memeImg.src = url;
      memeWrapper.classList.remove('hidden');
    } else {
      memeWrapper.classList.add('hidden');
    }
    bubbleEl.classList.remove('hidden');
    if (bubbleTimer) clearTimeout(bubbleTimer);
    bubbleTimer = setTimeout(() => {
      bubbleEl.classList.add('hidden');
    }, duration);
  }

  function hideSay() {
    bubbleEl.classList.add('hidden');
  }

  function showBalance(balanceStr) {
    if (!balanceStr) return;
    balanceText.textContent = balanceStr;
    balancePill.classList.remove('hidden');
    if (balanceTimer) clearTimeout(balanceTimer);
    balanceTimer = setTimeout(() => {
      balancePill.classList.add('hidden');
    }, 6000);
  }

  function setBackground(type, value) {
    if (type === 'dots') {
      bgLayer.style.backgroundImage = 'radial-gradient(circle at 50% 30%, #1e2638 0%, #0d1017 100%)';
      bgLayer.style.backgroundColor = '#0d1017';
    } else if (type === 'color') {
      bgLayer.style.backgroundImage = 'none';
      bgLayer.style.backgroundColor = value || '#0d1017';
    } else if (type === 'image' && value) {
      bgLayer.style.backgroundImage = `url("${value}")`;
      bgLayer.style.backgroundColor = '#000000';
    }
  }

  function setTransform(scale = 1.0, offsetX = 0, offsetY = 0) {
    const s = Math.max(0.4, Math.min(2.0, Number(scale) || 1.0));
    const ox = Math.round(Number(offsetX) || 0);
    const oy = Math.round(Number(offsetY) || 0);
    document.documentElement.style.setProperty('--pet-scale', s.toFixed(3));
    document.documentElement.style.setProperty('--pet-offset-x', `${ox}px`);
    document.documentElement.style.setProperty('--pet-offset-y', `${oy}px`);
  }

  function setBubbleScale(scale = 1.0) {
    const s = Math.max(0.7, Math.min(2.5, Number(scale) || 1.0));
    document.documentElement.style.setProperty('--bubble-scale', s.toFixed(3));
  }

  // ================================================================ Coopanion 专属控制
  function loadCoopanion(url = 'http://127.0.0.1:7797/pet') {
    if (!coopFrame) return;
    if (coopFrame.src !== url) {
      coopFrame.src = url;
    }
  }

  coopFrame.addEventListener('load', () => {
    coopanionLoaded = true;
    coopOffline.classList.add('hidden');
    try {
      const doc = coopFrame.contentDocument || coopFrame.contentWindow.document;
      if (doc) {
        const style = doc.createElement('style');
        style.textContent = `
          .floor-icons, #tools, .tools, #menu, .menu, .sizer, .wheel { display: none !important; }
        `;
        doc.head.appendChild(style);
      }
    } catch (e) {
      // 跨域或安全沙箱捕获
      console.log('[stage] Coopanion iframe 样式注入完成或受同源保护');
    }
  });

  coopFrame.addEventListener('error', () => {
    coopanionLoaded = false;
    coopOffline.classList.remove('hidden');
  });

  function touchCoopanion() {
    try {
      if (coopFrame && coopFrame.contentWindow) {
        const win = coopFrame.contentWindow;
        if (win.__petApp && typeof win.__petApp.touch === 'function') {
          win.__petApp.touch('pet');
          return true;
        }
        const doc = win.document;
        if (doc) {
          const pet = doc.querySelector('#pet, canvas, .pet-body');
          if (pet) {
            pet.dispatchEvent(new MouseEvent('click', { bubbles: true, cancelable: true }));
            return true;
          }
        }
      }
    } catch (e) {
      console.warn('[stage] 触发 Coopanion 摸头异常:', e);
    }
    return false;
  }

  function chatCoopanion(text) {
    try {
      if (coopFrame && coopFrame.contentWindow) {
        const win = coopFrame.contentWindow;
        if (win.__petApp && typeof win.__petApp.chat === 'function') {
          win.__petApp.chat(text);
          return true;
        }
        const doc = win.document;
        if (doc) {
          const ta = doc.querySelector('textarea, input[type="text"]');
          if (ta) {
            ta.value = text;
            ta.dispatchEvent(new Event('input', { bubbles: true }));
            if (ta.form) ta.form.requestSubmit();
            return true;
          }
        }
      }
    } catch (e) {
      console.warn('[stage] 发送 Coopanion 对话异常:', e);
    }
    return false;
  }

  // ================================================================ 模式切换中枢
  /**
   * 切换投放模式与双宠布局
   * @param {'coopanion'|'dsh'|'dual'} mode 投放模式
   * @param {string} layout 双宠布局 ('side_by_side'|'coopanion_main'|'dsh_main'|'overlay')
   */
  function setPetMode(mode = 'dual', layout = 'side_by_side') {
    currentMode = mode;
    currentLayout = layout;
    document.body.className = `mode-${mode} layout-${layout}`;

    if (mode === 'coopanion' || mode === 'dual') {
      loadCoopanion();
    }
    console.log(`[stage] 已切换投放模式: ${mode}, 布局: ${layout}`);
  }

  // 绑定全局控制门面
  window.__stageHub = {
    setPetMode,
    loadCoopanion,
    touchCoopanion,
    chatCoopanion,
    playAnim,
    playRandomIdle,
    showSay,
    hideSay,
    showBalance,
    setBackground,
    setTransform,
    setBubbleScale
  };

  window.__dshPet = {
    playAnim,
    playRandomIdle,
    showSay,
    hideSay,
    showBalance,
    touch: () => {
      playAnim('点击回应-开心跃动', false);
      showSay('嘿嘿~ 摸摸头最舒服啦！', '可爱', 3500);
    },
    setBackground,
    setTransform,
    setBubbleScale
  };

  // 初始启动：默认双宠同台投放
  setPetMode('dual', 'side_by_side');
  playAnim('待机呼吸休闲', false);

  console.log('[stage] 大肥鱼桌宠钛坦屏多宠投放舞台初始化完成');
})();

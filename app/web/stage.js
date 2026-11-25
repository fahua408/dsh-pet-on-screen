// stage.js — 大肥鱼桌宠钛坦屏 640×480 水冷舞台核心中枢（支持双宠同屏、单宠独立、睡眠循环与离线自愈）

(function () {
  'use strict';

  // DOM 节点引用
  const bgLayer = document.getElementById('bg-layer');
  const coopFrame = document.getElementById('coopanion-frame');
  const coopOffline = document.getElementById('coopanion-offline');

  const videoA = document.getElementById('video-a');
  const videoB = document.getElementById('video-b');
  const bubbleEl = document.getElementById('bubble-container');
  const bubbleText = document.getElementById('bubble-text');
  const memeWrapper = document.getElementById('bubble-meme-wrapper');
  const memeImg = document.getElementById('bubble-meme-img');
  const balancePill = document.getElementById('balance-pill');
  const balanceText = document.getElementById('balance-text');

  // 状态变量
  let activeVideo = videoA;
  let idleVideo = videoB;
  let currentAnimName = '';
  let pendingAnimName = '';
  let pendingStartTime = 0;
  let animGen = 0;
  let bubbleTimer = null;
  let balanceTimer = null;
  let pauseTimer = null;
  let idleTimer = null;
  let coopProbeTimer = null;
  let currentMode = 'dual';
  let currentLayout = 'side_by_side';
  let coopanionLoaded = false;
  let isSleeping = false;
  let lastAnimTime = 0;
  let lastWatchdogTime = -1;
  let lastWatchdogVideo = null;

  // WebM Blob 内存缓存（对齐 dsh-pet 官方 fetch+Blob 方案，彻底规避流式加载偶发 stalled 卡帧）
  const MAX_BLOB_CACHE = 24;
  const blobCache = new Map();
  const videoBlobUrls = new WeakMap();

  // 默认休闲动作轮播列表（优先排布动态感明显的动作，避免首屏长时间静止）
  const IDLE_ANIMATIONS = [
    '原地专心玩魔方',
    '悠闲哼歌',
    '原地漂浮踏步',
    '吃白饭',
    '深度思考碎碎念',
    '吃Token',
    '待机呼吸休闲'
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

  async function fetchAnimObjectUrl(animName) {
    const url = getAnimUrl(animName);
    let blob = blobCache.get(url);
    if (blob) {
      // 刷新 LRU 顺序
      blobCache.delete(url);
      blobCache.set(url, blob);
      return URL.createObjectURL(blob);
    }
    const resp = await fetch(url, { cache: 'force-cache' });
    if (!resp.ok) {
      throw new Error(`HTTP ${resp.status} for ${url}`);
    }
    blob = await resp.blob();
    if (blobCache.size >= MAX_BLOB_CACHE) {
      const oldestKey = blobCache.keys().next().value;
      if (oldestKey) blobCache.delete(oldestKey);
    }
    blobCache.set(url, blob);
    return URL.createObjectURL(blob);
  }

  function assignVideoObjectUrl(videoEl, objectUrl) {
    const prevUrl = videoBlobUrls.get(videoEl);
    if (prevUrl) {
      try { URL.revokeObjectURL(prevUrl); } catch (_) {}
    }
    videoBlobUrls.set(videoEl, objectUrl);
    videoEl.src = objectUrl;
  }

  function clearVideoTimers() {
    if (pauseTimer) {
      clearTimeout(pauseTimer);
      pauseTimer = null;
    }
    if (idleTimer) {
      clearTimeout(idleTimer);
      idleTimer = null;
    }
  }

  function scheduleNextIdle(delayMs = 0) {
    if (idleTimer) clearTimeout(idleTimer);
    if (delayMs <= 0) {
      idleTimer = null;
      playRandomIdle();
      return;
    }
    idleTimer = setTimeout(() => {
      idleTimer = null;
      playRandomIdle();
    }, delayMs);
  }

  /**
   * 双缓冲平滑播放 WebM 动作（fetch+Blob 零流式卡顿、代数防竞态、自愈看门狗）
   */
  function playAnim(animName, loop = false, fromSleepControl = false) {
    if (currentMode === 'coopanion' || !animName) return;
    if (isSleeping && !fromSleepControl && !animName.startsWith('睡觉-')) {
      isSleeping = false;
    }

    const now = Date.now();
    if (animName === pendingAnimName && now - pendingStartTime < 2500) {
      return;
    }
    if (animName === currentAnimName && !activeVideo.paused && !activeVideo.ended) {
      if (activeVideo.loop === loop && (loop || now - lastAnimTime < 900)) {
        return;
      }
    }
    lastAnimTime = now;
    currentAnimName = animName;
    pendingAnimName = animName;
    pendingStartTime = now;
    clearVideoTimers();

    const swapGen = ++animGen;
    const nextVideo = idleVideo;
    const prevVideo = activeVideo;

    nextVideo.onloadeddata = null;
    nextVideo.oncanplay = null;
    nextVideo.onended = null;
    nextVideo.onerror = null;
    nextVideo.loop = Boolean(loop);
    nextVideo.muted = true;
    nextVideo.autoplay = true;
    nextVideo.playsInline = true;
    nextVideo.playbackRate = 1.0;

    fetchAnimObjectUrl(animName).then((objectUrl) => {
      if (swapGen !== animGen || currentMode === 'coopanion') {
        try { URL.revokeObjectURL(objectUrl); } catch (_) {}
        return;
      }

      let readyHandled = false;
      let readyFallback = null;
      const onReady = () => {
        if (readyHandled) return;
        readyHandled = true;
        if (readyFallback) {
          clearTimeout(readyFallback);
          readyFallback = null;
        }
        nextVideo.onloadeddata = null;
        nextVideo.oncanplay = null;
        if (swapGen !== animGen || currentMode === 'coopanion') return;
        pendingAnimName = '';

        // 切至前台并清理旧视频的残留回调（防止后台旧视频触发 onended 打断当前动画）
        prevVideo.onended = null;
        prevVideo.onerror = null;
        prevVideo.onloadeddata = null;
        prevVideo.oncanplay = null;

        nextVideo.classList.add('is-front');
        prevVideo.classList.remove('is-front');
        activeVideo = nextVideo;
        idleVideo = prevVideo;

        nextVideo.play().catch((err) => {
          console.warn('[stage] 播放 WebM 异常:', err);
          if (!loop && !isSleeping) scheduleNextIdle(1200);
        });

        pauseTimer = setTimeout(() => {
          pauseTimer = null;
          if (idleVideo !== activeVideo) {
            try { idleVideo.pause(); } catch (_) {}
          }
        }, 180);
      };

      nextVideo.onloadeddata = onReady;
      nextVideo.oncanplay = onReady;
      nextVideo.onerror = () => {
        nextVideo.onloadeddata = null;
        nextVideo.oncanplay = null;
        if (swapGen !== animGen) return;
        pendingAnimName = '';
        console.warn('[stage] WebM 解码异常，自动回退待机:', animName);
        if (!isSleeping) scheduleNextIdle(800);
      };

      nextVideo.onended = (ev) => {
        if (ev && ev.currentTarget && !ev.currentTarget.classList.contains('is-front')) {
          return;
        }
        if (currentMode === 'coopanion') return;
        if (isSleeping) {
          if (animName === '睡觉-开始') {
            playAnim('睡觉-循环', true, true);
          }
          return;
        }
        if (!loop) {
          scheduleNextIdle();
        }
      };

      assignVideoObjectUrl(nextVideo, objectUrl);
      nextVideo.load();
      readyFallback = setTimeout(onReady, 220);
    }).catch((err) => {
      console.warn('[stage] 加载 WebM 资源失败:', animName, err);
      if (swapGen === animGen) {
        pendingAnimName = '';
        if (!isSleeping && currentMode !== 'coopanion') {
          scheduleNextIdle(1000);
        }
      }
    });
  }

  function playRandomIdle() {
    if (currentMode === 'coopanion' || isSleeping) return;
    const candidates = IDLE_ANIMATIONS.filter((a) => a !== currentAnimName);
    const pool = candidates.length > 0 ? candidates : IDLE_ANIMATIONS;
    const idx = Math.floor(Math.random() * pool.length);
    playAnim(pool[idx], false);
  }

  // 后台静默预热待机动作 Blob 缓存，确保动作切换 0 延迟无缝衔接
  async function prewarmIdleBlobs() {
    for (const name of IDLE_ANIMATIONS) {
      const url = getAnimUrl(name);
      if (!blobCache.has(url)) {
        try {
          const resp = await fetch(url, { cache: 'force-cache' });
          if (resp.ok) {
            const blob = await resp.blob();
            blobCache.set(url, blob);
          }
        } catch (_) {}
      }
    }
  }
  setTimeout(prewarmIdleBlobs, 700);

  // 视频播放自愈看门狗：每 3.5 秒巡检一次，若非睡眠状态下视频意外停滞且无待机定时器，立即唤醒下一动作
  setInterval(() => {
    if (currentMode === 'coopanion' || isSleeping) return;
    if (idleTimer !== null) return;
    if (pendingAnimName !== '') {
      if (Date.now() - pendingStartTime > 3000) {
        pendingAnimName = '';
        currentAnimName = '';
        playRandomIdle();
      }
      return;
    }
    const v = activeVideo;
    if (!v) return;
    if (v.paused || v.ended) {
      currentAnimName = '';
      playRandomIdle();
      return;
    }
    if (lastWatchdogVideo === v && Math.abs(v.currentTime - lastWatchdogTime) < 0.001 && v.readyState >= 2) {
      // 视频 currentTime 在 3.5 秒内完全未推进，触发自愈重播
      currentAnimName = '';
      playRandomIdle();
      return;
    }
    lastWatchdogVideo = v;
    lastWatchdogTime = v.currentTime;
  }, 3500);

  function setSleep(sleeping) {
    const target = Boolean(sleeping);
    if (target === isSleeping) return;
    isSleeping = target;
    clearVideoTimers();
    if (isSleeping) {
      playAnim('睡觉-开始', false, true);
      showSay('呼呼…先睡一会儿啦~ 💤', '深度睡眠', 4500);
    } else {
      playAnim('睡觉-起来', false, true);
      showSay('唔…睡饱啦，满血复活！✨', '可爱', 4000);
    }
  }

  function showSay(text, memeName = '', duration = 4500) {
    if (!text) return;
    bubbleText.textContent = text;
    if (memeName) {
      memeImg.src = getMemeUrl(memeName);
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
    if (bubbleTimer) clearTimeout(bubbleTimer);
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

  function setCoopanionScale(scale = 1.6) {
    const s = Math.max(0.8, Math.min(3.2, Number(scale) || 1.6));
    const cssScale = (s / 1.6) * 1.22;
    document.documentElement.style.setProperty('--coop-scale', cssScale.toFixed(3));
  }

  // ================================================================ Coopanion 专属控制（防错误页 + 离线自愈探测）
  async function probeAndLoadCoopanion(url = 'http://127.0.0.1:7797/pet') {
    if (!coopFrame || currentMode === 'dsh') return;
    try {
      const resp = await fetch('/api/coopanion_status', { cache: 'no-store' });
      const data = await resp.json();
      if (data && data.online) {
        if (!coopanionLoaded || coopFrame.src !== url) {
          coopanionLoaded = true;
          coopOffline.classList.add('hidden');
          coopFrame.src = url;
        }
        return;
      }
    } catch (_) {
      // 忽略异常并标记离线
    }
    coopanionLoaded = false;
    coopOffline.classList.remove('hidden');
    if (coopFrame.src && coopFrame.src !== 'about:blank') {
      coopFrame.src = 'about:blank';
    }
  }

  function startCoopanionMonitor() {
    if (coopProbeTimer) clearInterval(coopProbeTimer);
    probeAndLoadCoopanion();
    coopProbeTimer = setInterval(() => {
      if (currentMode === 'coopanion' || currentMode === 'dual') {
        probeAndLoadCoopanion();
      }
    }, 4000);
  }

  coopFrame.addEventListener('load', () => {
    if (!coopFrame.src || coopFrame.src === 'about:blank') return;
    try {
      const doc = coopFrame.contentDocument || (coopFrame.contentWindow && coopFrame.contentWindow.document);
      if (doc && doc.head) {
        const style = doc.createElement('style');
        style.textContent = `
          html, body { background: transparent !important; }
          .floor, .floor-icons, #tools, .tools, #menu, .menu, .sizer, .wheel { display: none !important; }
        `;
        doc.head.appendChild(style);
      }
    } catch (e) {
      // 跨域保护忽略
    }
  });

  function touchCoopanion() {
    try {
      if (coopFrame && coopFrame.contentWindow) {
        const win = coopFrame.contentWindow;
        if (win.__petApp && typeof win.__petApp.touch === 'function') {
          win.__petApp.touch('pet');
          return true;
        }
        if (win.__coopanionWs && win.__coopanionWs.readyState === 1) {
          win.__coopanionWs.send(JSON.stringify({ t: 'touch', kind: 'pat' }));
          return true;
        }
        const doc = win.document;
        if (doc) {
          const pet = doc.querySelector('#pet, canvas, .pet-body');
          if (pet) {
            const rect = pet.getBoundingClientRect();
            pet.dispatchEvent(new MouseEvent('click', {
              bubbles: true,
              cancelable: true,
              clientX: rect.left + rect.width * 0.5,
              clientY: rect.top + rect.height * 0.7
            }));
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
        if (typeof win.send === 'function') {
          win.send({ t: 'text', text: text });
          try { if (typeof win.addLine === 'function') win.addLine('type', text, false); } catch (_) {}
          return true;
        }
        if (win.__coopanionWs && win.__coopanionWs.readyState === 1) {
          win.__coopanionWs.send(JSON.stringify({ t: 'text', text: text }));
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
  function setPetMode(mode = 'dual', layout = 'side_by_side') {
    const prevMode = currentMode;
    currentMode = mode;
    currentLayout = layout;
    document.body.className = `mode-${mode} layout-${layout}`;

    if (mode === 'coopanion') {
      // 仅投放大肥鱼时暂停女仆 WebM 解码，避免后台消耗 CPU/GPU
      animGen++;
      pendingAnimName = '';
      clearVideoTimers();
      activeVideo.pause();
      idleVideo.pause();
      probeAndLoadCoopanion();
    } else {
      if (mode === 'dual') {
        probeAndLoadCoopanion();
      }
      if ((prevMode === 'coopanion' || activeVideo.paused) && !pendingAnimName) {
        if (isSleeping) {
          playAnim('睡觉-循环', true, true);
        } else {
          playAnim(currentAnimName || '原地专心玩魔方', false);
        }
      }
    }
  }

  window.__stageHub = {
    setPetMode,
    loadCoopanion: probeAndLoadCoopanion,
    touchCoopanion,
    chatCoopanion,
    playAnim,
    playRandomIdle,
    setSleep,
    showSay,
    hideSay,
    showBalance,
    setBackground,
    setTransform,
    setBubbleScale,
    setCoopanionScale
  };

  window.__dshPet = {
    playAnim,
    playRandomIdle,
    setSleep,
    showSay,
    hideSay,
    showBalance,
    touch: () => {
      if (isSleeping) {
        setSleep(false);
        return;
      }
      playAnim('点击回应-开心跃动', false);
      showSay('嘿嘿~ 摸摸头最舒服啦！', '可爱', 3500);
    },
    setBackground,
    setTransform,
    setBubbleScale
  };

  startCoopanionMonitor();
  setPetMode('dual', 'side_by_side');
})();

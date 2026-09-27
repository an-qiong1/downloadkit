// ========== 解答页（P1-5）==========
// 不占侧边栏：从设置页的内链进入，返回时回到「进来时的那个页面」。
// 页面本身是静态 HTML，这里只管进出、目录锚点和入口绑定。
(function() {
  'use strict';

  // 进解答页之前的页面，返回时回哪儿。初始值无意义，进过一次就会被覆盖。
  var backTab = 'settings';

  function gotoAnchor(id) {
    var el = document.getElementById(id);
    if (!el) return;
    // 用 auto 而不是 smooth：滚动容器是 .content（overflow:auto），
    // 平滑动画在部分环境里根本不跑，锚点就「点了没反应」。可靠优先。
    el.scrollIntoView({ behavior: 'auto', block: 'start' });
  }

  // 内容区是 .content 在滚（.main 是 overflow:hidden 的布局层）
  function scrollTop() {
    var scroller = document.querySelector('.content');
    if (scroller) scroller.scrollTop = 0;
  }

  function openHelp(anchor) {
    // 只有从别的页面进来才记来源页；解答页内跳目录不覆盖，
    // 否则「解答 → 目录 → 返回」会退回解答页自己。
    if (state.activeTab !== 'help') {
      backTab = state.activeTab || 'settings';
    }
    state.activeTab = 'help';

    $$('.nav-item').forEach(function(item) {
      item.classList.remove('active');
    });
    $$('.tab-panel').forEach(function(panel) {
      panel.classList.toggle('active', panel.id === 'panel-help');
    });
    $('#page-title').textContent = tabTitles['help'] || '解答';

    if (typeof window.__closeSidebar === 'function') window.__closeSidebar();

    scrollTop();
    if (anchor) gotoAnchor(anchor);
  }

  function closeHelp() {
    var target = (backTab && backTab !== 'help') ? backTab : 'settings';
    if (typeof window.__switchTab === 'function') {
      window.__switchTab(target);
    } else {
      // app.js 还没就绪的兜底：至少把面板切回去，别把人困在解答页
      state.activeTab = target;
      $$('.tab-panel').forEach(function(panel) {
        panel.classList.toggle('active', panel.id === 'panel-' + target);
      });
      $('#page-title').textContent = tabTitles[target] || target;
    }
  }

  window.openHelp = openHelp;
  window.closeHelp = closeHelp;

  // —— 绑定 ——
  var backBtn = $('#help-back');
  if (backBtn) backBtn.addEventListener('click', closeHelp);

  // 设置页「关于」组的入口
  var openBtn = $('#open-help');
  if (openBtn) {
    openBtn.addEventListener('click', function() {
      openHelp();
    });
  }

  // 左侧目录锚点
  $$('.help-toc-link').forEach(function(link) {
    link.addEventListener('click', function() {
      gotoAnchor(link.dataset.anchor);
    });
  });

  // 设置页里所有 data-help 入口（长说明被挪到这里之后，原位置留的「详细说明」链接）
  $$('[data-help]').forEach(function(el) {
    el.addEventListener('click', function(e) {
      e.preventDefault();
      openHelp(el.dataset.help || undefined);
    });
  });
})();

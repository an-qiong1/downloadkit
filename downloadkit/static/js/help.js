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

    // 每次进来重置搜索：带着上次的关键词进来会看到半页空白，
    // 得先反应一下才知道是过滤没清
    resetSearch();

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

  // —— 搜索过滤（P3-3）——
  // 两级粒度：块级（help-block 整块）+ 行级（li / 表格数据行 / dt+dd 对 /
  // 独立段落）。块标题命中 = 整块相关，内部全部恢复；否则按行过滤，
  // 一行都不剩的块连同它的目录项一起藏，全藏完露空状态。
  var searchInput = $('#help-search');

  function textOf(el) {
    return ((el && el.textContent) || '').toLowerCase();
  }

  // 复原整块：块本身 + 所有被行级过滤藏过的元素
  function showBlock(block) {
    block.style.display = '';
    $$('li, p, tr, dt, dd', block).forEach(function(el) {
      el.style.display = '';
    });
  }

  function resetSearch() {
    if (searchInput) searchInput.value = '';
    filterHelp();
  }

  function filterHelp() {
    if (!searchInput) return;
    var q = (searchInput.value || '').trim().toLowerCase();
    var visibleBlocks = 0;

    $$('.help-block').forEach(function(block) {
      if (!q) {
        showBlock(block);
        visibleBlocks++;
        return;
      }

      var h4 = block.querySelector('h4');
      if (h4 && textOf(h4).indexOf(q) >= 0) {
        showBlock(block);
        visibleBlocks++;
        return;
      }

      var rowHit = false;
      function applyRow(el) {
        var hit = textOf(el).indexOf(q) >= 0;
        el.style.display = hit ? '' : 'none';
        if (hit) rowHit = true;
      }

      // dt+dd 成对判定：只命中一边就整对留下，否则会出现
      // 只有问题没答案（或反过来）的残缺条目
      $$('dt', block).forEach(function(dt) {
        var sib = dt.nextElementSibling;
        var dd = (sib && sib.tagName === 'DD') ? sib : null;
        var hit = textOf(dt).indexOf(q) >= 0 || (dd && textOf(dd).indexOf(q) >= 0);
        dt.style.display = hit ? '' : 'none';
        if (dd) dd.style.display = hit ? '' : 'none';
        if (hit) rowHit = true;
      });

      // 表格数据行；表头永远留着，行藏光了列名不能也丢
      $$('tr', block).forEach(function(tr) {
        if (tr.closest('thead')) return;
        applyRow(tr);
      });

      $$('li', block).forEach(applyRow);
      // 只过滤独立段落；li 里嵌的 p 跟 li 走，单独拆会把一条
      // 命中的 li 挖掉半截内容
      $$('p', block).filter(function(p) { return !p.closest('li'); })
        .forEach(applyRow);

      if (rowHit) {
        block.style.display = '';
        visibleBlocks++;
      } else {
        block.style.display = 'none';
      }
    });

    // 目录跟着内容走：块都藏了，入口留着点过去也是一片空白
    $$('.help-toc-link').forEach(function(link) {
      var target = document.getElementById(link.dataset.anchor);
      link.style.display = (target && target.style.display !== 'none') ? '' : 'none';
    });

    var empty = $('#help-empty');
    if (empty) empty.style.display = (q && visibleBlocks === 0) ? '' : 'none';
  }

  // —— 绑定 ——
  if (searchInput) searchInput.addEventListener('input', filterHelp);

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

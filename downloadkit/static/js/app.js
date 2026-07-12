(function() {
  'use strict';
  
  // ========== 侧边栏切换 ==========
  function switchTab(tab) {
    var navItem = $('.nav-item[data-tab="' + tab + '"]');
    if (navItem && navItem.classList.contains('disabled')) {
      return;
    }
    
    state.activeTab = tab;
    
    $$('.nav-item').forEach(function(item) {
      item.classList.toggle('active', item.dataset.tab === tab);
    });
    
    $$('.tab-panel').forEach(function(panel) {
      panel.classList.toggle('active', panel.id === 'panel-' + tab);
    });
    
    $('#page-title').textContent = tabTitles[tab] || tab;
    
    if (tab === 'files') {
      refreshFiles();
    }
    
    if (tab === 'queue') {
      refreshQueue();
    }
    
    if (tab === 'settings') {
      if (typeof loadSettings === 'function') loadSettings();
    }
    
    closeSidebar();
  }
  
  $$('.nav-item').forEach(function(item) {
    item.addEventListener('click', function() {
      switchTab(item.dataset.tab);
    });
  });
  
  // ========== 移动端侧边栏 ==========
  function openSidebar() {
    $('#sidebar').classList.add('open');
    $('#sidebar-overlay').classList.add('show');
  }
  
  function closeSidebar() {
    $('#sidebar').classList.remove('open');
    $('#sidebar-overlay').classList.remove('show');
  }
  
  $('#menu-btn').addEventListener('click', openSidebar);
  $('#sidebar-overlay').addEventListener('click', closeSidebar);
  
  // ========== 初始化 ==========
  lucide.createIcons();
  
  refreshFiles();
  startQueueAutoRefresh();
})();

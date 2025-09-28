// Client-side helper for Strategy Signals page
// Fetch paginated results from /api/strategy_signals and render them.
(function(){
  const searchEl = document.getElementById('signalsSearch');
  const body = document.getElementById('signalsTableBody');
  let page = 1, per_page = 50, total = 0;
  let debounceTimer = null;

  function toLocal(iso){
    if(!iso) return '-';
    try{
      const d = new Date(iso);
      return d.toLocaleString();
    }catch(e){
      return iso;
    }
  }

  function formatPrice(px){
    if(px===null || px===undefined) return '₹N/A';
    try{
      return '₹' + Number(px).toFixed(6);
    }catch(e){
      return String(px);
    }
  }

  function renderRows(items){
    if(!body) return;
    body.innerHTML = '';
    items.forEach((r,i)=>{
      const tr = document.createElement('tr');
      tr.innerHTML = `
        <td>${(page-1)*per_page + i + 1}</td>
        <td><span class="badge bg-light text-dark">${r.strategy||''}</span></td>
        <td>${r.symbol||''}</td>
        <td><span class="badge bg-success text-white">${r.type||''}</span></td>
        <td><span class="badge bg-secondary">${r.status||''}</span></td>
        <td>${formatPrice(r.entry_price)}</td>
        <td>${formatPrice(r.exit_price)}</td>
        <td>${toLocal(r.entry_time)}</td>
        <td>${toLocal(r.exit_time)}</td>
        <td><span class="badge bg-danger">${r.trading_status||''}</span></td>
        <td>${r.exit_reason||''}</td>
      `;
      body.appendChild(tr);
    });
  }

  async function fetchPage(p=1){
    page = p;
    const q = new URLSearchParams();
    q.set('page', page);
    q.set('per_page', per_page);
    const term = (searchEl && searchEl.value) ? searchEl.value.trim() : '';
    if(term) q.set('symbol', term);
    try{
      const resp = await fetch('/api/strategy_signals?'+q.toString(), { headers: {'Accept': 'application/json'} });
      if(!resp.ok) return;
      const js = await resp.json();
      total = js.total_setups || 0;
      renderRows(js.items || []);
    }catch(e){
      console.error('fetch error', e);
    }
  }

  function onSearchChange(){
    if(debounceTimer) clearTimeout(debounceTimer);
    debounceTimer = setTimeout(()=>{ fetchPage(1); }, 350);
  }

  document.addEventListener('DOMContentLoaded', ()=>{
    // Only enable dynamic fetch if server didn't render rows
    if(body && body.children.length === 0){
      fetchPage(1);
    }
    if(searchEl){
      searchEl.addEventListener('input', onSearchChange);
    }
  });
})();

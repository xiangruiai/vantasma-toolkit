var blocks = document.querySelectorAll('.weui-desktop-block');
var results = [];
blocks.forEach(function(b) {
  var card = b.querySelector('.weui-desktop-mass-appmsg');
  if (!card) return;
  var dateEl = b.querySelector('[class*=date], [class*=time]');
  var title = card.querySelector('.weui-desktop-mass-appmsg__title');
  var url = '';
  if (title) {
    var a = title.closest('a') || title.querySelector('a');
    if (a && a.href && a.href.indexOf('mp.weixin.qq.com') > -1) {
      url = a.href;
    }
  }
  if (!url) {
    var aTag = card.querySelector('a[href*="mp.weixin.qq.com/s"]');
    if (aTag) url = aTag.href;
  }
  if (!url) {
    var el = card.querySelector('[data-url], [data-link]');
    if (el) url = el.getAttribute('data-url') || el.getAttribute('data-link') || '';
  }
  if (!url) {
    var allLinks = card.querySelectorAll('a[href]');
    for (var i = 0; i < allLinks.length; i++) {
      var h = allLinks[i].href;
      if (h && h.indexOf('/s/') > -1 && h.indexOf('mp.weixin') > -1) {
        url = h; break;
      }
    }
  }
  var view = card.querySelector('.appmsg-view');
  var share = card.querySelector('.appmsg-share');
  var haokan = card.querySelector('.appmsg-haokan');
  var like = card.querySelector('.appmsg-like');
  results.push({
    t: title ? title.innerText.trim().split('\n')[0] : '',
    u: url,
    r: parseInt((view ? view.innerText.trim() : '0').replace(/,/g, '')) || 0,
    s: parseInt((share ? share.innerText.trim() : '0').replace(/,/g, '')) || 0,
    w: parseInt((haokan ? haokan.innerText.trim() : '0').replace(/,/g, '')) || 0,
    l: parseInt((like ? like.innerText.trim() : '0').replace(/,/g, '')) || 0,
    d: dateEl ? dateEl.innerText.trim() : ''
  });
});
JSON.stringify(results);
